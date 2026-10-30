# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The projection cache: one sqlite row per document, kept in the writable
runtime dir (NOT inside the corpus — see runtime.corpus_path). The SOLE writer
of the cache. It is rebuildable — never a source of truth.

The cache runs its OWN tree-poller (the service's concern, not the engine's:
two independent readers of one filesystem doing different jobs). It carries
the engine watcher's settle discipline in one specific shape — a sidecar that
cannot be read or verified right now (a torn mid-write, an integrity blip) is
SKIPPED and retried on the next tick, never thrown. That is the single place
the no-fallbacks rule yields, because here a half-written file is expected
concurrency, not a violated invariant — and it is the service's concern alone,
since only the reader-that-does-not-write meets a file mid-write."""
import json
import sqlite3
import threading
from pathlib import Path

import yaml

from shapes.corpus.engine import identity, sidecar
from shapes.corpus.service import payloads, runtime

# areas the cache projects (everything the engine settles a document into)
_AREAS = ("working", "corpus", "retired", "quarantine", "failed")


def _locked(method):
    """Serialize every SQLite touch: the poller thread writes while FastAPI
    request threads read the one connection. RLock so a locked method may call
    another (rebuild → reconcile)."""
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class Cache:
    def __init__(self, corpus_dir: Path, flow: dict):
        self.corpus_dir = corpus_dir
        self.flow = flow
        self.declared = set(_declared_fields(flow))
        self.operator_fields = set(_operator_fields(flow))
        self._last_inbox_docs: set = set()   # doc_ids with an in-flight assert
        self._lock = threading.RLock()       # serializes the shared connection
        # The cache db lives in the runtime dir, NOT inside the corpus — the
        # corpus is a read-only artifact the serve never writes. Rebuildable, so
        # a fresh db on each start is correct; reconcile refolds the tree into it.
        db = runtime.corpus_path(corpus_dir, "catalogue.sqlite")
        self.db = sqlite3.connect(db, check_same_thread=False)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS rows (
                doc_id TEXT PRIMARY KEY, status TEXT, mtime REAL,
                lens_hard INT, lens_soft INT, lens_retired INT, lens_quarantine INT,
                row_json TEXT)""")
        self.db.commit()

    # --- maintenance --------------------------------------------------------

    @_locked
    def rebuild(self) -> list:
        self.db.execute("DELETE FROM rows")
        self.db.commit()
        return self.reconcile()

    @_locked
    def reconcile(self) -> list:
        """Fold every readable pair; drop cached rows no longer on disk."""
        on_disk = {}
        for meta in identity.iter_pairs(self.corpus_dir, areas=_AREAS):
            on_disk[meta.parent.name] = meta
        cached = {r[0] for r in self.db.execute("SELECT doc_id FROM rows")}
        for doc_id in cached - set(on_disk):
            self.db.execute("DELETE FROM rows WHERE doc_id = ?", (doc_id,))
        changed = []
        for doc_id, meta in on_disk.items():
            if self._upsert(doc_id, meta):
                changed.append({"doc_id": doc_id, "change": "sidecar"})
        self.db.commit()
        return changed

    @_locked
    def tick(self) -> list:
        """Incremental: refold pairs whose sidecar mtime changed, drop vanished
        ones. A torn/unreadable sidecar is skipped (retried next tick)."""
        on_disk = {}
        for meta in identity.iter_pairs(self.corpus_dir, areas=_AREAS):
            on_disk[meta.parent.name] = meta
        stored = {r[0]: r[1] for r in
                  self.db.execute("SELECT doc_id, mtime FROM rows")}
        changed = []
        for doc_id in set(stored) - set(on_disk):
            self.db.execute("DELETE FROM rows WHERE doc_id = ?", (doc_id,))
            changed.append({"doc_id": doc_id, "change": "removed"})
        for doc_id, meta in on_disk.items():
            try:
                mtime = meta.stat().st_mtime
            except OSError:
                continue
            if doc_id in stored and stored[doc_id] == mtime:
                continue
            kind = "sidecar" if doc_id in stored else "moved"
            if self._upsert(doc_id, meta):
                changed.append({"doc_id": doc_id, "change": kind})
        # inbox asserts change a row's pending markers without touching its
        # sidecar — refresh any doc whose in-flight-assert state changed, so the
        # ◌ appears when the assert lands and clears when the engine consumes it.
        already = {c["doc_id"] for c in changed}
        inbox_docs = self._docs_with_inbox()
        for doc_id in (inbox_docs | self._last_inbox_docs) - already:
            meta = on_disk.get(doc_id)
            if meta is not None and self._upsert(doc_id, meta):
                changed.append({"doc_id": doc_id, "change": "sidecar"})
        self._last_inbox_docs = inbox_docs
        self.db.commit()
        return changed

    def _docs_with_inbox(self) -> set:
        """doc_ids with an assert sitting in inbox/ (the ◌-bearing docs)."""
        inbox = self.corpus_dir / "inbox"
        docs: set = set()
        if inbox.is_dir():
            for f in inbox.glob("*.assert.yaml"):
                docs.add(f.name.removesuffix(".assert.yaml").rsplit("-", 1)[-1])
        return docs

    def _upsert(self, doc_id: str, meta: Path) -> bool:
        """Fold one pair and write its row. Returns True on success, False if
        the sidecar could not be read/verified now (skip, retry next tick)."""
        try:
            doc = sidecar.read(meta)
            if "stages" not in doc or "status" not in doc:
                return False
            pending = self._pending_for(doc_id)
            row = payloads.build_row(doc, self.declared, pending)
            mtime = meta.stat().st_mtime
            status = doc["status"]
            hard = 1 if status.startswith(("parked@", "failed@")) else 0
            # operator_fields ⊆ declared, so a missing one is absent from the
            # row's cells — no second fold needed for the soft-queue flag.
            soft = 1 if (status == "complete" and
                         any(f not in row["cells"] for f in self.operator_fields)) else 0
            retired = 1 if status == "retired" else 0
            quar = 1 if status == "quarantined" else 0
            self.db.execute(
                "REPLACE INTO rows VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, status, mtime, hard, soft, retired, quar,
                 json.dumps(row)))
        except Exception:
            return False     # torn/unreadable/malformed: retry on the next tick
        return True

    def _pending_for(self, doc_id: str) -> list:
        """Declared fields named by an assert sitting in inbox/ for this doc,
        not yet consumed by the engine — the ◌ markers."""
        inbox = self.corpus_dir / "inbox"
        names: list = []
        if inbox.is_dir():
            for f in inbox.glob(f"*-{doc_id}.assert.yaml"):
                try:
                    payload = yaml.safe_load(f.read_text())
                    names.extend((payload.get("fields") or {}).keys())
                except Exception:
                    continue
        return names

    # --- reads --------------------------------------------------------------

    @_locked
    def lens_counts(self) -> dict:
        r = self.db.execute(
            "SELECT COUNT(*), SUM(lens_hard), SUM(lens_soft), "
            "SUM(lens_retired), SUM(lens_quarantine) FROM rows").fetchone()
        return {"all": r[0] or 0, "hard": r[1] or 0, "soft": r[2] or 0,
                "retired": r[3] or 0, "quarantine": r[4] or 0}

    @_locked
    def facets(self) -> dict:
        counts = self.db.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN lens_hard=1 OR lens_soft=1 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status='complete' AND lens_soft=0 THEN 1 ELSE 0 END) "
            "FROM rows").fetchone()
        facets = [{"key": "status", "values": [
            {"value": "all", "count": counts[0] or 0},
            {"value": "pending", "count": counts[1] or 0},
            {"value": "done", "count": counts[2] or 0}]}]
        rows = [json.loads(rj) for (rj,) in
                self.db.execute("SELECT row_json FROM rows")]
        for name, declared_values in _enum_fields(self.flow):
            tally: dict = {}
            for r in rows:
                cell = r.get("cells", {}).get(name)
                if not cell:
                    continue
                v = cell["value"]
                for item in (v if isinstance(v, list) else [v]):
                    tally[item] = tally.get(item, 0) + 1
            values = [{"value": dv, "count": tally[dv]}
                      for dv in declared_values if dv in tally]
            facets.append({"key": name, "values": values})
        return {"facets": facets}

    @_locked
    def catalogue(self, lens: str = "all", where: dict | None = None,
                  cursor: int = 0, limit: int = 100) -> dict:
        clause, params = self._lens_clause(lens)
        sql = f"SELECT doc_id, row_json FROM rows{clause} ORDER BY doc_id"
        rows = [json.loads(rj) for _, rj in self.db.execute(sql, params)]
        if where:
            rows = [r for r in rows if _matches(r, where)]
        total = len(rows)
        page = rows[cursor:cursor + limit]
        next_cursor = cursor + limit if cursor + limit < total else None
        return {"rows": page, "cursor": next_cursor, "total": total}

    @_locked
    def row(self, doc_id: str) -> dict | None:
        r = self.db.execute(
            "SELECT row_json FROM rows WHERE doc_id = ?", (doc_id,)).fetchone()
        return json.loads(r[0]) if r else None

    def _lens_clause(self, lens: str):
        if lens == "pending":
            return " WHERE (lens_hard = 1 OR lens_soft = 1)", ()
        if lens == "done":
            return " WHERE status = 'complete' AND lens_soft = 0", ()
        col = {"hard": "lens_hard", "soft": "lens_soft",
               "retired": "lens_retired", "quarantine": "lens_quarantine"}.get(lens)
        if col is None:
            return "", ()
        return f" WHERE {col} = 1", ()


def _matches(row: dict, where: dict) -> bool:
    """Equality on declared fields and derived status; a set field means
    membership; conjunction only."""
    for key, value in where.items():
        if key == "status":
            if row["status"] != value:
                return False
            continue
        if key == "tag":
            tags = (row["cells"].get("tags") or {}).get("value") or []
            if value not in tags:
                return False
            continue
        cell = row["cells"].get(key)
        if cell is None:
            return False
        cv = cell["value"]
        if isinstance(cv, list):
            if value not in cv:
                return False
        elif cv != value:
            return False
    return True


def _declared_fields(flow: dict) -> list:
    fields = list((flow.get("fields") or {}).keys())
    for stage in flow.get("pipeline", []):
        fields.extend((stage.get("fields") or {}).keys())
    return fields


def _enum_fields(flow: dict) -> list:
    """(name, declared_values) for each declared field of type 'enum', in
    declaration order, de-duplicated. The facetable fields — type 'string'
    fields (free text) are never facets."""
    seen: set = set()
    out: list = []
    sources = [flow.get("fields") or {}]
    for stage in flow.get("pipeline", []):
        sources.append(stage.get("fields") or {})
    for fields in sources:
        for name, decl in fields.items():
            if name in seen or decl.get("type") != "enum":
                continue
            seen.add(name)
            out.append((name, list(decl.get("values", []))))
    return out


def _operator_fields(flow: dict) -> list:
    """Fields an operator is expected to fill — flow-level fields whose `by:`
    admits operator. A complete doc missing one of these is in the soft queue."""
    out = []
    for name, decl in (flow.get("fields") or {}).items():
        by = decl.get("by", "model")
        if by == "operator" or (isinstance(by, list) and "operator" in by):
            out.append(name)
    return out


def _field_specs(flow: dict) -> dict:
    """Full field spec for every declared field: type, values (if enum),
    of (if set), by. Scans flow-level and stage-level fields, de-duplicated."""
    specs: dict = {}
    sources = [flow.get("fields") or {}]
    for stage in flow.get("pipeline", []):
        sources.append(stage.get("fields") or {})
    for fields in sources:
        for name, decl in fields.items():
            if name in specs:
                continue
            spec = {"type": decl["type"], "by": decl.get("by", "model")}
            if decl.get("values"):
                spec["values"] = list(decl["values"])
            if decl.get("of"):
                spec["of"] = decl["of"]
            specs[name] = spec
    return specs
