# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus ls <path> — one folded row per completed document."""
from pathlib import Path

import yaml

from shapes.corpus.commands._read import load, resolve_corpus
from shapes.corpus.engine import identity
from shapes.corpus.engine.assert_inbox import _declared


def _load_flow(corpus: Path) -> dict:
    corpus_doc = yaml.safe_load((corpus / "corpus.yaml").read_text())
    flow_path = (corpus / corpus_doc["flow"]).resolve()
    return yaml.safe_load(flow_path.read_text())


def run(corpus_root: Path, instance: str, args: list) -> None:
    corpus = resolve_corpus(args)
    flow = _load_flow(corpus)
    declared = _declared(flow)
    for meta in identity.iter_pairs(corpus, areas=("corpus",)):
        doc, projection = load(meta)
        desc = "  ".join(
            f"{k}={v}" for k, v in projection.items() if k in declared)
        print(f"{doc['doc_id']}  {desc}")