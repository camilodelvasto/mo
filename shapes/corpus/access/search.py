# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Doc-level full-text search for the catalogue: reconcile the index, run lexical
(BM25) retrieval, roll chunk hits up to distinct documents. No LLM, no synthesis —
the catalogue filter's content half. Semantic retrieval stays in run_ask."""
from pathlib import Path

from shapes.corpus.access import index, reconcile, retrieve


def search_docs(corpus: Path, machine_root: Path, q: str, k: int = 200) -> list:
    """Documents whose chunk text matches q, best-first, one entry per doc.
    Reconcile-before-search guarantees the index reflects the current corpus
    (closes the 'recently ingested' gap). k caps chunk hits before rollup."""
    q = q.strip()
    if not q:
        return []
    reconcile.reconcile(corpus, machine_root, vectors=False)  # text/FTS only — lexical
    # search must never wait on the embedder (a 45-doc backfill froze the TUI)
    conn = index.open_index(corpus)
    try:
        hits = retrieve.retrieve(conn, "lexical", k, None, q, None)
    finally:
        conn.close()
    docs: dict = {}
    for h in hits:                          # hits are pre-ordered best-first (bm25)
        doc_id = h["doc_id"]
        if doc_id not in docs:              # first occurrence = this doc's best hit
            docs[doc_id] = {"doc_id": doc_id, "score": h["score"], "snippet": h["text"]}
    return list(docs.values())
