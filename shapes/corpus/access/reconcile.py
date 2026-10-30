# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The ONLY writer of index/. Diff corpus/ + retired/ against the db; embed new
chunks (ref-keyed), drop retired/removed, refresh changed projections.
Idempotent. Runs before every ask. See GUIDE.md."""
import json
import shutil
from pathlib import Path

from shapes.corpus.access import index, passport
from shapes.corpus.access.askfile import declared_embedder
from shapes.corpus.engine import identity, sidecar
from shapes.corpus.engine.fold import fold


def _present(corpus: Path) -> dict[str, Path]:
    """doc_id -> bundle dir for every completed bundle in corpus/."""
    out = {}
    base = corpus / "corpus"
    if base.is_dir():
        for meta in identity.iter_pairs(corpus, areas=("corpus",)):
            out[meta.parent.name] = meta.parent
    return out


def _load_chunks(bundle: Path) -> list[dict]:
    path = bundle / "chunks.jsonl"
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def reconcile(corpus: Path, machine_root: Path, rebuild: bool = False,
              vectors: bool = True) -> dict:
    """vectors=False indexes text/FTS/projection only and leaves embeddings
    pending — for lexical consumers (the catalogue search) that must not pay
    the embedding cost. Vector consumers reconcile with vectors=True (default),
    which also completes anything left pending."""
    if rebuild and index.db_path(corpus).exists():
        shutil.rmtree(corpus / "index")

    lexical = declared_embedder(corpus) is None
    present = _present(corpus)

    # First build (or post-rebuild): branch on lexical vs embedded.
    if not index.db_path(corpus).exists():
        if lexical:
            conn = index.open_index(corpus)  # dim=None → FTS-only schema
            passport.write_lexical(corpus)
        else:
            ident = passport.probe(corpus, machine_root)
            conn = index.open_index(corpus, dim=ident["dimension"])
            passport.write(corpus, ident)
    else:
        # Throws on divergence. The live probe only runs when this reconcile
        # will use the embedder (vectors) — a lexical read doesn't.
        passport.verify(corpus, machine_root, lexical=lexical, probe_live=vectors)
        conn = index.open_index(corpus)

    try:
        in_db = {r[0]: r[1] for r in conn.execute("SELECT doc_id, meta_hash FROM docs")}
        embedded = dropped = refreshed = vectored = 0

        # Drop anything no longer present in corpus/ (retired or removed).
        for doc_id in set(in_db) - set(present):
            _drop(conn, doc_id, lexical); dropped += 1

        for doc_id, bundle in present.items():
            meta_hash = identity.sha256_file(bundle / "meta.yaml")
            if doc_id not in in_db:
                _index_doc(conn, doc_id, bundle)
                _refresh_projection(conn, doc_id, bundle)
                conn.execute("INSERT INTO docs(doc_id, meta_hash) VALUES (?,?)",
                             (doc_id, meta_hash))
                embedded += 1
            elif in_db[doc_id] != meta_hash:
                _refresh_projection(conn, doc_id, bundle)
                conn.execute("UPDATE docs SET meta_hash=? WHERE doc_id=?",
                             (meta_hash, doc_id))
                refreshed += 1

        if not lexical and vectors:
            conn.commit()          # land the text index before the slow vector
            vectored = _embed_pending(conn, machine_root)  # phase; commits per doc
        pending = 0 if lexical else conn.execute(
            "SELECT count(DISTINCT doc_id) FROM chunks "
            "WHERE rowid NOT IN (SELECT rowid FROM vec_chunks)").fetchone()[0]

        conn.commit()
        total = conn.execute("SELECT count(*) FROM docs").fetchone()[0]
    finally:
        conn.close()
    return {"embedded": embedded, "dropped": dropped, "refreshed": refreshed,
            "vectored": vectored, "pending": pending, "total": total}


def _index_doc(conn, doc_id: str, bundle: Path) -> None:
    """Text + FTS only — never spawns the embedder. Vectors are a separate
    pass (_embed_pending) so lexical consumers don't wait on them."""
    for chunk in _load_chunks(bundle):
        cur = conn.execute(
            "INSERT INTO chunks(doc_id, ref, span_start, span_end, text) "
            "VALUES (?,?,?,?,?)",
            (doc_id, chunk["ref"], chunk["span"][0], chunk["span"][1], chunk["text"]))
        conn.execute("INSERT INTO fts_chunks(rowid, text) VALUES (?,?)",
                     (cur.lastrowid, chunk["text"]))


def _embed_pending(conn, machine_root: Path) -> int:
    """Embed every chunk that has no vector yet, doc by doc, committing after
    each — the write lock is held per doc, never across the batch, and an
    interrupted backfill keeps every doc it finished. Reconciles run
    concurrently (every ask runs one), so the pending list scanned up front is
    a snapshot: the write lock is taken BEFORE re-checking what is still
    pending, and only that is inserted — a doc another writer just landed is
    skipped, never double-inserted. Returns docs completed."""
    rows = conn.execute(
        "SELECT rowid, doc_id, ref, text FROM chunks "
        "WHERE rowid NOT IN (SELECT rowid FROM vec_chunks) ORDER BY doc_id").fetchall()
    by_doc: dict[str, list] = {}
    for rowid, doc_id, ref, text in rows:
        by_doc.setdefault(doc_id, []).append((rowid, ref, text))
    for doc_id, items in by_doc.items():
        chunks = [{"ref": ref, "text": text} for _, ref, text in items]
        vectors = passport.embed(chunks, machine_root)  # slow; runs outside the lock
        conn.execute("BEGIN IMMEDIATE")
        still = {r[0] for r in conn.execute(
            "SELECT rowid FROM chunks WHERE doc_id=? AND rowid NOT IN "
            "(SELECT rowid FROM vec_chunks)", (doc_id,))}
        # embed() returns vectors in chunk order, so pair by position: a ref is a
        # content hash and two identical passages in one doc share it — keying by
        # ref would land the same rowid twice.
        for (rowid, _, _), vec in zip(items, vectors):
            if rowid in still:
                conn.execute("INSERT INTO vec_chunks(rowid, doc_id, embedding) VALUES (?,?,?)",
                             (rowid, doc_id, index.serialize(vec["vector"])))
        conn.commit()
    return len(by_doc)


def _drop(conn, doc_id: str, lexical: bool = False) -> None:
    rowids = [r[0] for r in conn.execute(
        "SELECT rowid FROM chunks WHERE doc_id=?", (doc_id,))]
    for rowid in rowids:
        if not lexical:
            conn.execute("DELETE FROM vec_chunks WHERE rowid=?", (rowid,))
        conn.execute("DELETE FROM fts_chunks WHERE rowid=?", (rowid,))
    conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM projection WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM docs WHERE doc_id=?", (doc_id,))


def _refresh_projection(conn, doc_id: str, bundle: Path) -> None:
    doc = sidecar.read(bundle / "meta.yaml")
    folded = fold(doc.get("stages", []))
    conn.execute(
        "INSERT INTO projection(doc_id, folded) VALUES (?,?) "
        "ON CONFLICT(doc_id) DO UPDATE SET folded=excluded.folded",
        (doc_id, json.dumps(folded, ensure_ascii=False)))
