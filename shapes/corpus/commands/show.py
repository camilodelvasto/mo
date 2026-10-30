# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus show <path> <doc_id> — projection plus provenance."""
import sys
from pathlib import Path

from shapes.corpus.commands._read import load, resolve_corpus
from shapes.corpus.engine import identity


def run(corpus_root: Path, instance: str, args: list) -> None:
    corpus = resolve_corpus(args)
    if len(args) < 2:
        print("usage: mo corpus show <path> <doc_id>", file=sys.stderr)
        sys.exit(1)
    doc_id = args[1]
    meta = identity.find_pair(corpus, doc_id)
    if meta is None:
        print(f"no document {doc_id} in {corpus}", file=sys.stderr)
        sys.exit(1)
    doc, projection = load(meta)
    print(f"doc_id: {doc['doc_id']}   status: {doc['status']}")
    for name, value in projection.items():
        provenance = _contributor(doc["stages"], name)
        print(f"  {name}: {value}    [{provenance}]")


def _contributor(stages: list, name: str) -> str:
    """The entry whose fields last touched this name (sets: last touch)."""
    winner = "?"
    for entry in stages:
        if name in (entry.get("fields") or {}):
            winner = entry.get("id", "?")
    return winner