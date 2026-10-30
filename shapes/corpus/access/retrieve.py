# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Mode dispatch (vector|lexical|hybrid|none) + rrf fusion, scoped to a doc_id
set. One function takes the mode, runs what it names, returns a uniform ranked
result with per-chunk provenance. scope=None means all docs; scope=set() means
no docs (an empty result)."""
import re

from shapes.corpus.access import index

_RRF_K = 60  # reciprocal rank fusion constant; combine by rank, no score tuning


def retrieve(conn, mode: str, k: int, scope, question: str, embed) -> list:
    if mode == "none":
        return []
    if scope is not None and len(scope) == 0:
        return []
    if mode == "vector":
        return _hydrate(conn, _vector(conn, question, k, scope, embed), "vector")
    if mode == "lexical":
        return _hydrate(conn, _lexical(conn, question, k, scope), "lexical")
    if mode == "hybrid":
        return _fuse(conn, _vector(conn, question, k, scope, embed),
                     _lexical(conn, question, k, scope), k)
    raise ValueError(f"unknown retrieve mode: {mode!r}")


def retrieve_many(conn, mode: str, k: int, scope, queries: list, embed) -> list:
    """Retrieve for each query independently, then RRF-fuse the ranked passage lists
    into one top-k. A single query behaves exactly like retrieve(). Fusion keys on
    chunk identity (doc_id, ref): a chunk surfaced by two queries reinforces, so a
    minority-intent doc that ranks #1 for its own query survives the merge."""
    if len(queries) == 1:
        return retrieve(conn, mode, k, scope, queries[0], embed)
    scores: dict = {}
    first: dict = {}
    for q in queries:
        for rank, p in enumerate(retrieve(conn, mode, k, scope, q, embed)):
            key = (p["doc_id"], p["ref"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
            first.setdefault(key, p)
    order = sorted(scores, key=lambda key: scores[key], reverse=True)[:k]
    out = []
    for key in order:
        p = dict(first[key])
        p["score"] = scores[key]
        out.append(p)
    return out


def _scope_clause(scope, col: str) -> tuple[str, list]:
    if scope is None:
        return "", []
    marks = ",".join("?" for _ in scope)
    return f" AND {col} IN ({marks})", list(scope)


def _vector(conn, question: str, k: int, scope, embed) -> list[tuple[int, float]]:
    if conn.execute("SELECT 1 FROM chunks WHERE rowid NOT IN "
                    "(SELECT rowid FROM vec_chunks) LIMIT 1").fetchone():
        raise ValueError("vector retrieval refused: chunks with pending embeddings "
                         "in the index — run a full reconcile first")
    qvec = index.serialize(embed(question))
    clause, params = _scope_clause(scope, "doc_id")
    sql = ("SELECT rowid, distance FROM vec_chunks "
           f"WHERE embedding MATCH ? AND k = ?{clause} ORDER BY distance")
    rows = conn.execute(sql, [qvec, k, *params]).fetchall()
    return [(r[0], r[1]) for r in rows]


def _fts_query(question: str) -> str:
    """Strip characters that FTS5 treats as syntax (punctuation, not word/space).
    A question like "¿qué dicen?" becomes "qué dicen" — the words still match."""
    return re.sub(r"[^\w\s]", " ", question, flags=re.UNICODE).strip()


def _lexical(conn, question: str, k: int, scope) -> list[tuple[int, float]]:
    q = _fts_query(question)
    if not q:
        return []
    clause, params = _scope_clause(scope, "c.doc_id")
    sql = ("SELECT f.rowid, bm25(fts_chunks) AS rank "
           "FROM fts_chunks f JOIN chunks c ON c.rowid = f.rowid "
           f"WHERE fts_chunks MATCH ?{clause} ORDER BY rank LIMIT ?")
    rows = conn.execute(sql, [q, *params, k]).fetchall()
    return [(r[0], r[1]) for r in rows]


def _hydrate(conn, ranked: list, retriever: str) -> list:
    out = []
    for rowid, score in ranked:
        row = conn.execute(
            "SELECT doc_id, ref, span_start, span_end, text FROM chunks WHERE rowid=?",
            (rowid,)).fetchone()
        out.append({"doc_id": row[0], "ref": row[1], "span": [row[2], row[3]],
                    "text": row[4], "score": float(score), "retriever": retriever})
    return out


def _fuse(conn, vec: list, lex: list, k: int) -> list:
    scores: dict[int, float] = {}
    seen: dict[int, set] = {}
    for ranked, name in ((vec, "vector"), (lex, "lexical")):
        for rank, (rowid, _) in enumerate(ranked):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (_RRF_K + rank)
            seen.setdefault(rowid, set()).add(name)
    order = sorted(scores, key=lambda r: scores[r], reverse=True)[:k]
    out = []
    for rowid in order:
        row = conn.execute(
            "SELECT doc_id, ref, span_start, span_end, text FROM chunks WHERE rowid=?",
            (rowid,)).fetchone()
        retr = "both" if len(seen[rowid]) == 2 else next(iter(seen[rowid]))
        out.append({"doc_id": row[0], "ref": row[1], "span": [row[2], row[3]],
                    "text": row[4], "score": scores[rowid], "retriever": retr})
    return out
