# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Post-retrieval stitching: widen each hit with its adjacent chunks (same doc,
span order) so a passage never ends mid-argument. Contiguous runs — a hit plus
its neighbors, or two hits that turn out adjacent — merge into ONE passage, so
the model never reads the same text twice. A merged passage keeps the
highest-ranked member hit as its citable anchor (`ref`, `score`, `retriever`)
and lists every member in `refs` so citation checking accepts any of them.
Pure read over the chunks table; input rank is preserved, never re-sorted
(scores are not comparable across retrieval modes). radius 0 is identity."""


def stitch(conn, passages: list, radius: int) -> list:
    if radius == 0 or not passages:
        return passages
    by_doc: dict = {}
    for rank, p in enumerate(passages):
        by_doc.setdefault(p["doc_id"], []).append((rank, p))
    runs = []                       # (best_rank, doc_id, chunks, member_indices, best_hit)
    for doc_id, hits in by_doc.items():
        chunks = conn.execute(
            "SELECT ref, span_start, span_end, text FROM chunks "
            "WHERE doc_id = ? ORDER BY span_start", (doc_id,)).fetchall()
        pos = {row[0]: i for i, row in enumerate(chunks)}
        covered = set()
        for _, h in hits:
            i = pos[h["ref"]]       # absent ref = index/lake mismatch: let it throw
            covered.update(range(max(0, i - radius), min(len(chunks), i + radius + 1)))
        for indices in _contiguous(sorted(covered)):
            members = set(indices)
            best_rank, best = min(
                (rank, h) for rank, h in hits if pos[h["ref"]] in members)
            runs.append((best_rank, doc_id, chunks, indices, best))
    runs.sort(key=lambda r: r[0])
    out = []
    for _, doc_id, chunks, indices, best in runs:
        rows = [chunks[i] for i in indices]
        out.append({"doc_id": doc_id, "ref": best["ref"],
                    "refs": [r[0] for r in rows],
                    "span": [rows[0][1], rows[-1][2]],
                    "text": "\n\n".join(r[3] for r in rows),
                    "score": best["score"], "retriever": best["retriever"]})
    return out


def _contiguous(indices: list) -> list:
    groups: list = []
    for i in indices:
        if groups and i == groups[-1][-1] + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups
