# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus status <path> — a count per area, one screen."""
from collections import Counter
from pathlib import Path

from shapes.corpus.commands._read import area_of, resolve_corpus
from shapes.corpus.engine import identity


def run(corpus_root: Path, instance: str, args: list) -> None:
    corpus = resolve_corpus(args)
    counts: Counter = Counter()
    for meta in identity.iter_pairs(corpus):
        counts[area_of(corpus, meta)] += 1
    for area in sorted(counts):
        print(f"{area:<24} {counts[area]}")
    orphans = identity.find_orphans(corpus)
    if not counts and not orphans:
        print("empty corpus — nothing in any area")
    
    if orphans:
        missing_sidecar = sum(1 for f in orphans if f["kind"] == "missing-sidecar")
        missing_file = sum(1 for f in orphans if f["kind"] == "missing-file")
        torn = sum(1 for f in orphans if f["kind"] == "torn-sidecar")
        if missing_sidecar:
            print(f"{'orphans: missing sidecar':<24} {missing_sidecar}")
        if missing_file:
            print(f"{'orphans: missing file':<24} {missing_file}")
        if torn:
            print(f"{'orphans: torn sidecar':<24} {torn}")