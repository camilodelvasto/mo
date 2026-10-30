# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The loop. Given a reaction (a dropped file, an assert, a flow change,
a resumable pair), compute the next step and take it. Re-checks parked: and
re-evaluates rules: after every appended entry.

Across pairs the pool parallelizes; within a pair, one reaction at a time —
_in_flight serializes per doc_id."""
import hashlib
import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema
import yaml

from collections import deque

from shapes.corpus.engine import capabilities, identity, runner, rules, sidecar
from shapes.corpus.engine.errors import (ContractError, CorpusError,
                                         IntegrityError, StageFailure)
from shapes.corpus.engine.observer import ConsoleObserver
from shapes.corpus.engine.fold import fold
from shapes.corpus.engine.watcher import Watcher

POOL_SIZE = 4
_SCHEMA_DIR = Path(__file__).parent.parent / "schemas"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: Path, schema_name: str) -> dict:
    if not path.is_file():
        raise ContractError(f"missing: {path}")
    doc = yaml.safe_load(path.read_text())
    schema = json.loads((_SCHEMA_DIR / schema_name).read_text())
    try:
        jsonschema.validate(doc, schema)
    except jsonschema.ValidationError as exc:
        raise ContractError(f"{path} invalid against {schema_name}: {exc.message}") from exc
    return doc


def _check_branch_adjacency(flow: dict) -> None:
    """Branch stages (repeated ids) must be consecutive: _next_due walks
    groups positionally, so a non-adjacent repeat would skip stages."""
    seen: list = []
    for stage in flow["pipeline"]:
        sid = stage["id"]
        if sid in seen and seen[-1] != sid:
            raise ContractError(
                f"stage id {sid!r} repeats non-consecutively; branches must be adjacent")
        seen.append(sid)


class Engine:
    def __init__(self, corpus_dir: Path, machine_root: Path,
                 pool_size: int = POOL_SIZE, observer=None, resume: bool = True):
        self.corpus_dir = corpus_dir
        self.machine_root = machine_root
        self.pool_size = pool_size
        self.observer = observer if observer is not None else ConsoleObserver(0)
        self.corpus = _load_yaml(corpus_dir / "corpus.yaml", "corpus.v1.json")
        self.flow = self._load_flow()
        self.table = capabilities.load_table(machine_root)
        from shapes.corpus.builtins import REGISTRY, rename
        self._names_originals = rename.names_originals
        self.builtin_names = set(REGISTRY)
        capabilities.verify(self.flow, self.table, self.builtin_names)

        self.watcher = Watcher(corpus_dir, self.flow["entrypoints"])
        self.pool = ThreadPoolExecutor(max_workers=pool_size)
        self._queues: dict[str, deque] = {}    # doc_id -> pending jobs, FIFO
        self._in_flight: set[str] = set()
        self._halted: set[str] = set()
        self._lock = threading.Lock()
        self._futures: list = []
        if resume:
            self._resume_all()    # crash recovery: pairs sitting in working/
        self._report_orphans()

    # --- the loop -----------------------------------------------------------

    def run(self) -> None:
        while True:
            self.tick()
            time.sleep(1)

    def tick(self) -> None:
        for event in self.watcher.tick():
            # Daemon boundary, same as _work: one bad event — a vanished file,
            # an OSError mid-handler, a rejected flow edit — is surfaced loud
            # and skipped. It never escapes run() and crashes the watcher.
            try:
                if event.kind == "dropped":
                    self._on_drop(event.path, event.entrypoint)
                elif event.kind == "assert":
                    self._on_assert(event.path)
                elif event.kind == "order":
                    self._on_order(event.path)
                elif event.kind == "flow-changed":
                    self._on_flow_changed()
            except CorpusError as exc:
                if event.kind == "flow-changed":
                    # a rejected edit is NOT adopted; in-flight pairs are safe
                    # on their snapshots. Next save retries.
                    self.observer.emit("flow-not-adopted", reason=str(exc))
                else:
                    self.observer.emit("error", reason=f"{event.kind}: {exc}")
            except Exception as exc:
                self.observer.emit("error", reason=(
                    f"{event.kind}: unexpected {type(exc).__name__}: {exc}"))

    def drain(self) -> None:
        """Tests: wait for everything submitted so far."""
        while True:
            with self._lock:
                futures, self._futures = self._futures, []
            if not futures:
                return
            for f in futures:
                f.result()

    # --- per-document serialization (load-bearing — see GUIDE.md) ------------
    # Across pairs the pool parallelizes; within a pair, one reaction at a
    # time. Every reaction is a job on the document's FIFO queue; one worker
    # drains a document's queue, so jobs never interleave and never get lost.

    def _submit(self, doc_id: str, job) -> None:
        with self._lock:
            if doc_id in self._halted:
                return
            self._queues.setdefault(doc_id, deque()).append(job)
            if doc_id in self._in_flight:
                return            # the running worker will drain it
            self._in_flight.add(doc_id)
            self._futures.append(self.pool.submit(self._work, doc_id))

    def _work(self, doc_id: str) -> None:
        while True:
            with self._lock:
                queue = self._queues.get(doc_id)
                if not queue:
                    self._queues.pop(doc_id, None)
                    self._in_flight.discard(doc_id)
                    return
                job = queue.popleft()
            try:
                job()
            except IntegrityError as exc:
                self.observer.emit("halted", doc_id=doc_id, reason=str(exc))
                with self._lock:
                    self._halted.add(doc_id)
                    self._queues.pop(doc_id, None)
                    self._in_flight.discard(doc_id)
                return
            except CorpusError as exc:
                self.observer.emit("error", doc_id=doc_id, reason=str(exc))
            except Exception as exc:  # the daemon boundary: surfaced loud, never wedged
                self.observer.emit("error", doc_id=doc_id,
                                   reason=f"unexpected {type(exc).__name__}: {exc}")
                with self._lock:
                    self._queues.pop(doc_id, None)
                    self._in_flight.discard(doc_id)
                return

    # --- reactions ----------------------------------------------------------

    def _on_drop(self, path: Path, entrypoint: dict) -> None:
        doc_id = identity.doc_id_for(path)
        existing = identity.find_pair(self.corpus_dir, doc_id)
        if existing is not None:
            drop_hash = identity.sha256_file(path)
            source_name = path.name
            path.unlink()         # discard now — the next tick must not re-see it
            pair_dir = existing.parent

            def duplicate_job():
                entry = {"id": "received-duplicate", "entrypoint": entrypoint["id"],
                         "at": _now(), "hash": drop_hash, "fields": {}}
                # a flow that renames originals refused the dropped name once;
                # the log must not take it in through the back door
                if not self._names_originals(self._contract_for(pair_dir)):
                    entry["source_name"] = source_name
                sidecar.append(pair_dir / "meta.yaml", entry)
                self.observer.emit("duplicate", doc_id=doc_id, source_name=source_name)
                self._advance(pair_dir)

            self._submit(doc_id, duplicate_job)
            return
        pair_dir = self.corpus_dir / "working" / "stamp" / doc_id
        pair_dir.mkdir(parents=True)
        original = pair_dir / path.name
        shutil.move(path, original)
        snapshot = pair_dir / "flow.snapshot.yaml"
        shutil.copyfile(self.corpus_dir / "flow.yaml", snapshot)
        flow_hash = "sha256:" + hashlib.sha256(snapshot.read_bytes()).hexdigest()
        sidecar.write(pair_dir / "meta.yaml", {
            "doc_id": doc_id,
            "flow": {"id": self.flow["id"],
                     "version": self.flow["version"], "hash": flow_hash},
            "status": "in-flight@stamp",
            "stages": [{
                "id": "received", "entrypoint": entrypoint["id"], "at": _now(),
                "hash": identity.sha256_file(original),
                "fields": dict(entrypoint.get("fields") or {}),
            }],
            "artifacts": {
                "meta": {"path": "./meta.yaml"},
                "original": {"path": f"./{original.name}", "kept": True},
            },
        })
        self.observer.emit("dropped", doc_id=doc_id, entrypoint=entrypoint["id"])
        self._submit(doc_id, lambda: self._advance(pair_dir))

    def _on_assert(self, path: Path) -> None:
        # filename is <ulid>-<doc_id>.assert.yaml: the doc_id keys the queue,
        # so an assert never interleaves with a stage on the same pair
        doc_id = path.name.removesuffix(".assert.yaml").rsplit("-", 1)[-1]

        def assert_job():
            from shapes.corpus.engine import assert_inbox
            target = assert_inbox.process(self.corpus_dir, path, self.flow)
            if target is None:
                return
            pair_dir = target.parent
            # an assert on a failed pair is the operator saying "try again": move
            # it back to working/<stage> so _advance re-runs the failed stage —
            # the same recovery restart_failed performs, now triggered per-pair.
            if pair_dir.parent.parent.name == "failed":
                stage_id = pair_dir.parent.name
                pair_dir = self._move(pair_dir, None,
                                      self.corpus_dir / "working" / stage_id,
                                      f"in-flight@{stage_id}")
            self._advance(pair_dir)

        self._submit(doc_id, assert_job)

    def _on_order(self, path: Path) -> None:
        doc_id = path.name.removesuffix(".order.yaml").rsplit("-", 1)[-1]

        def order_job():
            from shapes.corpus.engine import order_inbox
            result = order_inbox.process(self.corpus_dir, path)
            if result is None:
                return                     # rejected to failed/inbox/
            action, target = result
            if action == "retire":
                self._retire(target.parent, {"by": "operator", "via": "order"})
            path.unlink(missing_ok=True)   # success path only: rejected orders
                                           # were already moved by order_inbox

        self._submit(doc_id, order_job)

    def _on_flow_changed(self) -> None:
        """Validated and adopted for new arrivals; in-flight pairs hold
        their pinned snapshot. Migration is deliberate, never a side effect."""
        flow = self._load_flow()
        capabilities.verify(flow, self.table, self.builtin_names)
        self.flow = flow
        self.watcher.entrypoints = self.flow["entrypoints"]
        self.observer.emit("flow-adopted", version=self.flow["version"])

    def reevaluate(self, pair_dir: Path) -> None:
        """Any reaction touching an existing pair funnels through here."""
        self._submit(pair_dir.name, lambda: self._advance(pair_dir))

    def restart_failed(self) -> None:
        """Re-run the due stage of every pair in failed/<stage>/ — a corrupt
        file repaired, a tool upgraded, a transient error gone. Parked pairs
        are not restart's business: they wait for asserts."""
        for meta in identity.iter_pairs(self.corpus_dir, areas=("failed",)):
            pair_dir = meta.parent
            stage_id = pair_dir.parent.name
            if stage_id == "inbox":
                continue              # rejected asserts are fixed and re-dropped
            moved = self._move(pair_dir, None,
                               self.corpus_dir / "working" / stage_id,
                               f"in-flight@{stage_id}")
            self._submit(moved.name, lambda p=moved: self._resume_job(p))

    def reprocess(self, doc_ids: list[str] | None, from_stage: str | None) -> int:
        """Re-run documents under the current flow. from_stage rewinds to that
        stage, reusing every artifact produced before it; None re-runs from the
        original. Returns the count reprocessed; skips (missing doc, broken
        chain, not past from_stage) are surfaced via the observer and excluded."""
        pipeline_ids = [s["id"] for s in self.flow["pipeline"]]
        if from_stage is not None and from_stage not in pipeline_ids:
            raise ContractError(
                f"--from: no stage {from_stage!r} in the current flow "
                f"(stages: {', '.join(pipeline_ids)})")
        cut = pipeline_ids.index(from_stage) if from_stage is not None else 0
        drop_ids = set(pipeline_ids[cut:])
        required_before = set(pipeline_ids[:cut])
        entry_stage = from_stage if from_stage is not None else pipeline_ids[0]

        if doc_ids:
            metas = []
            for did in doc_ids:
                m = identity.find_pair(self.corpus_dir, did)
                if m is None:
                    self.observer.emit("error", doc_id=did,
                                       reason="reprocess: no such document")
                    continue
                metas.append(m)
        else:
            metas = list(identity.iter_pairs(
                self.corpus_dir, areas=("corpus", "working", "failed")))

        done = 0
        for meta in metas:
            pair_dir = meta.parent
            try:
                moved = self._rewind(pair_dir, drop_ids, required_before,
                                     from_stage, entry_stage)
            except CorpusError as exc:
                self.observer.emit("error", doc_id=pair_dir.name,
                                   reason=f"reprocess: {exc}")
                continue
            self._submit(moved.name, lambda p=moved: self._resume_job(p))
            done += 1
        return done

    def _rewind(self, pair_dir: Path, drop_ids: set, required_before: set,
                from_stage: str | None, entry_stage: str) -> Path:
        meta = pair_dir / "meta.yaml"
        sidecar.verify_chain(pair_dir)                 # tampered/torn → IntegrityError
        doc = sidecar.read_verified(meta)
        logged = {e["id"] for e in doc["stages"]}
        missing = required_before - logged
        if missing:
            raise ContractError(
                f"not past {from_stage}: missing {', '.join(sorted(missing))}")

        prior_hash = doc["integrity"]["hash"]
        prior_flow_version = doc["flow"]["version"]

        kept = [e for e in doc["stages"] if e["id"] not in drop_ids]
        kept_arts = {e["output"]["artifact"] for e in kept
                     if e.get("output") and e["output"].get("artifact")}

        # A kept artifact whose on-disk bytes were rewritten by a dropped stage
        # cannot be reused — the original bytes are gone. Detect before mutating
        # and skip the doc rather than strand it on a later verify_chain halt.
        latest_kept_output = {}
        for e in kept:
            out = e.get("output") or {}
            if out.get("artifact") and "hash" in out:
                latest_kept_output[out["artifact"]] = out["hash"]
        for art, want in latest_kept_output.items():
            fname = Path(doc["artifacts"][art]["path"]).name
            have = identity.sha256_file(pair_dir / fname)
            if have != want:
                raise ContractError(
                    f"cannot reuse {art!r}: rewritten by a dropped stage "
                    f"downstream — rewind earlier or omit --from")

        for e in doc["stages"]:
            if e["id"] in drop_ids:
                art = (e.get("output") or {}).get("artifact")
                if art and art not in kept_arts and art in doc.get("artifacts", {}):
                    fname = Path(doc["artifacts"][art]["path"]).name
                    (pair_dir / fname).unlink(missing_ok=True)
                    doc["artifacts"].pop(art, None)

        snapshot = pair_dir / "flow.snapshot.yaml"
        shutil.copyfile(self.corpus_dir / "flow.yaml", snapshot)
        flow_hash = "sha256:" + hashlib.sha256(snapshot.read_bytes()).hexdigest()
        doc["flow"] = {"id": self.flow["id"],
                       "version": self.flow["version"], "hash": flow_hash}

        kept.append({"id": "reprocessed", "from": from_stage,
                     "prior_hash": prior_hash,
                     "prior_flow_version": prior_flow_version,
                     "flow_version": self.flow["version"], "at": _now()})
        doc["stages"] = kept
        doc["status"] = f"in-flight@{entry_stage}"
        sidecar.write(meta, doc)                       # re-stamp the rewound chain
        return self._move(pair_dir, doc,
                          self.corpus_dir / "working" / entry_stage,
                          f"in-flight@{entry_stage}")

    def _resume_job(self, pair_dir: Path) -> None:
        sidecar.verify_chain(pair_dir)
        self._advance(pair_dir)

    # --- the walk -----------------------------------------------------------

    def _advance(self, pair_dir: Path) -> None:
        while True:
            meta = pair_dir / "meta.yaml"
            doc = sidecar.read_verified(meta)
            contract = self._contract_for(pair_dir)
            projection = fold(doc["stages"])

            for rule in rules.due_rules(contract, projection):
                if rule["do"] == "retire":
                    self._retire(pair_dir, {"rule": rule["when"]})
                    return

            area = pair_dir.parent.parent.name if pair_dir.parent.parent != self.corpus_dir \
                else pair_dir.parent.name
            if area not in ("working",):
                return            # complete/failed/quarantined/retired: rules only

            parked_names, parked_stage = self._unsatisfied_park(doc, projection)
            if parked_names:
                self._set_status(pair_dir, doc, f"parked@{parked_stage}")
                self.observer.emit("parked", doc_id=pair_dir.name,
                                   stage=parked_stage, fields=parked_names)
                return

            stage = self._next_due(pair_dir, doc, contract)
            if stage is None:
                self._complete(pair_dir)
                return
            pair_dir = self._move(pair_dir, None,
                                  self.corpus_dir / "working" / stage["id"],
                                  f"in-flight@{stage['id']}")
            try:
                entry = runner.run_stage(pair_dir, stage, contract, self.table,
                                         self.observer)
            except StageFailure as exc:
                sidecar.append(pair_dir / "meta.yaml", {
                    "id": stage["id"], "at": _now(), "failed": exc.reason, "fields": {},
                })
                handler = stage.get("on_fail", "fail")
                if handler == "quarantine":
                    dest, status = self.corpus_dir / "quarantine", "quarantined"
                    self.observer.emit("quarantined", doc_id=pair_dir.name,
                                       stage=stage["id"])
                else:
                    dest = self.corpus_dir / f"failed/{stage['id']}"
                    status = f"failed@{stage['id']}"
                    self.observer.emit("failed", doc_id=pair_dir.name,
                                       stage=stage["id"], reason=exc.reason)
                self._move(pair_dir, None, dest, status)
                return
            value_handler = self._value_handler(stage, entry)
            if value_handler == "quarantine":
                self._move(pair_dir, None, self.corpus_dir / "quarantine", "quarantined")
                return
            # loop: rules re-checked, park re-checked, next stage computed

    def _next_due(self, pair_dir: Path, doc: dict, contract: dict) -> dict | None:
        # a failure entry does NOT count as the stage having run — that is
        # exactly what --restart re-runs after a repair
        logged = {e["id"] for e in doc["stages"] if "failed" not in e}
        projection = fold(doc["stages"])
        stages = contract["pipeline"]
        i = 0
        while i < len(stages):
            group = [s for s in stages if s["id"] == stages[i]["id"]]
            sid = stages[i]["id"]
            i += len(group)
            if sid in logged:
                continue
            chosen = None
            for branch in group:
                if "when" not in branch or rules.evaluate_condition(branch["when"], projection):
                    chosen = branch
                    break
            if chosen is not None:
                return chosen
            conditions = "; ".join(b["when"] for b in group)
            doc = sidecar.append(pair_dir / "meta.yaml",
                                 {"id": sid, "skipped": conditions, "fields": {}})
        return None

    def _unsatisfied_park(self, doc: dict, projection: dict) -> tuple[list[str], str | None]:
        names: list[str] = []
        stage_id: str | None = None
        for entry in doc["stages"]:
            if entry.get("parked"):
                names, stage_id = entry["parked"], entry["id"]
        return [n for n in names if n not in projection], stage_id

    def _value_handler(self, stage: dict, entry: dict) -> str | None:
        for key, action in stage.items():
            if key.startswith("on_") and key != "on_fail":
                if key[3:] in [str(v) for v in entry.get("fields", {}).values()]:
                    return action
        return None

    # --- moves (location is status; move + status write are one operation) ---

    def _move(self, pair_dir: Path, doc: dict | None, dest_parent: Path, status: str) -> Path:
        meta = pair_dir / "meta.yaml"
        doc = doc if doc is not None else sidecar.read_verified(meta)
        if pair_dir.parent == dest_parent:
            self._set_status(pair_dir, doc, status)
            return pair_dir
        doc["status"] = status
        sidecar.write(meta, doc)
        sidecar.forget(meta)
        dest_parent.mkdir(parents=True, exist_ok=True)
        dest = dest_parent / pair_dir.name
        pair_dir.rename(dest)
        sidecar.write(dest / "meta.yaml", doc)   # re-register the new path
        return dest

    def _set_status(self, pair_dir: Path, doc: dict, status: str) -> None:
        if doc["status"] != status:
            doc["status"] = status
            sidecar.write(pair_dir / "meta.yaml", doc)

    def _complete(self, pair_dir: Path) -> None:
        (pair_dir / "flow.snapshot.yaml").unlink(missing_ok=False)
        self._move(pair_dir, None, self.corpus_dir / "corpus", "complete")
        self.observer.emit("complete", doc_id=pair_dir.name)

    def _retire(self, pair_dir: Path, trigger: dict) -> None:
        """One retirement mechanic, two callers: the flow's rule (trigger
        {'rule': <when>}) and a manual operator order (trigger
        {'by': 'operator', 'via': 'order'}). The trigger fields go straight
        into the appended entry; the move and the once-only guard are shared."""
        if pair_dir.parent.name == "retired":
            return            # location is status: retirement happened once
        doc = sidecar.append(pair_dir / "meta.yaml", {
            "id": "retired", "at": _now(), "fields": {}, **trigger,
        })
        self._move(pair_dir, doc, self.corpus_dir / "retired", "retired")
        self.observer.emit("retired", doc_id=pair_dir.name,
                           rule=trigger.get("rule", trigger.get("via", "unknown")))

    # --- startup ------------------------------------------------------------

    def _load_flow(self) -> dict:
        rel = self.corpus["flow"]
        flow = _load_yaml((self.corpus_dir / rel).resolve(), "flow.v1.json")
        _check_branch_adjacency(flow)
        return flow

    def _contract_for(self, pair_dir: Path) -> dict:
        snapshot = pair_dir / "flow.snapshot.yaml"
        if snapshot.is_file():
            return _load_yaml(snapshot, "flow.v1.json")
        return self.flow      # completed/retired: the log stays open under
                                  # the current contract (plan decision 1)

    def _resume_all(self) -> None:
        for meta in identity.iter_pairs(self.corpus_dir, areas=("working",)):
            pair_dir = meta.parent
            self._submit(pair_dir.name, lambda p=pair_dir: self._resume_job(p))

    def _report_orphans(self) -> None:
        for finding in identity.find_orphans(self.corpus_dir):
            if finding["kind"] == "torn-sidecar":
                self.observer.emit("orphan", target=finding["meta"].parent.name,
                                   detail="sidecar unreadable")
            elif finding["kind"] == "missing-sidecar":
                self.observer.emit("orphan", target=str(finding["pair_dir"]),
                                   detail="no sidecar — flagged, not moved")
            else:
                self.observer.emit("orphan", target=finding["meta"].parent.name,
                                   detail=f"manifest names {finding['path']} "
                                          "but the file is gone")
