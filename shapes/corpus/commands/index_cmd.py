# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus index <path> [--rebuild] — reconcile the index against the lake."""
from pathlib import Path

import yaml

from shapes.corpus.access import reconcile
from shapes.corpus.builtins import REGISTRY
from shapes.corpus.commands._read import resolve_corpus
from shapes.corpus.engine import capabilities


def run(corpus_root: Path, instance: str, args: list) -> None:
    corpus = resolve_corpus(args)
    rebuild = "--rebuild" in args

    corpus_doc = yaml.safe_load((corpus / "corpus.yaml").read_text())
    flow = yaml.safe_load((corpus / corpus_doc["flow"]).resolve().read_text())
    table = capabilities.load_table(corpus_root)
    capabilities.verify(flow, table, set(REGISTRY))

    summary = reconcile.reconcile(corpus, corpus_root, rebuild=rebuild)
    print(f"indexed: {summary['embedded']} new, {summary['dropped']} dropped, "
          f"{summary['refreshed']} refreshed  ({summary['total']} docs)")
