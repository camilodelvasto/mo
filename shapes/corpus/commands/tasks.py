# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus tasks <path> — the actionable queue: working/ and failed/."""
from pathlib import Path

from shapes.corpus.commands._read import area_of, load, resolve_corpus
from shapes.corpus.engine import identity


def _area_of_dir(corpus_dir: Path, pair_dir: Path) -> str:
    """area string from a pair directory (no meta.yaml needed)."""
    rel = pair_dir.relative_to(corpus_dir)
    return "/".join(rel.parts[:-1]) if len(rel.parts) > 1 else rel.parts[0]


def run(corpus_root: Path, instance: str, args: list) -> None:
    corpus = resolve_corpus(args)
    rows = 0
    for meta in identity.iter_pairs(corpus, areas=("working", "failed")):
        doc, projection = load(meta)
        area = area_of(corpus, meta)
        names, stage_id, failed = [], None, None
        for entry in doc["stages"]:
            if entry.get("parked"):
                names, stage_id = entry["parked"], entry["id"]
            if entry.get("failed"):
                failed = entry["failed"]
        unsatisfied = [n for n in names if n not in projection]
        note = ("parked: " + ", ".join(unsatisfied)) if unsatisfied else (
            f"failed: {failed}" if failed else "")
        print(f"{doc['doc_id']}  {area:<22} {note}")
        rows += 1
    for finding in identity.find_orphans(corpus):
        if finding["kind"] == "torn-sidecar":
            meta = finding["meta"]
            print(f"{meta.parent.name}  {area_of(corpus, meta):<22} ORPHAN: torn sidecar")
            rows += 1
            continue
        if finding["kind"] == "missing-sidecar":
            pair_dir = finding["pair_dir"]
            area = _area_of_dir(corpus, pair_dir)
            print(f"{pair_dir.name}  {area:<22} ORPHAN: no sidecar")
        else:
            meta = finding["meta"]
            path = finding["path"]
            doc_id = meta.parent.name
            area = area_of(corpus, meta)
            print(f"{doc_id}  {area:<22} ORPHAN: missing {path}")
        rows += 1
    if not rows:
        print("no tasks — nothing in working/ or failed/")