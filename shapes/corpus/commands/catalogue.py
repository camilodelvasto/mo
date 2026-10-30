# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus catalogue <corpus> — the read-only catalogue TUI (embed mode)."""
import sys
from pathlib import Path

import yaml

from shapes.corpus.commands._read import resolve_corpus
from shapes.corpus.renderer.tui.app import CatalogueApp
from shapes.corpus.service.cache import _declared_fields


def run(corpus_root: Path, instance: str, args: list) -> None:
    unknown = [a for a in args if a.startswith("-")]
    if unknown:
        print(f"unknown flag(s): {' '.join(unknown)}", file=sys.stderr)
        sys.exit(1)
    corpus = resolve_corpus([a for a in args if not a.startswith("-")])
    corpus_doc = yaml.safe_load((corpus / "corpus.yaml").read_text())
    flow = yaml.safe_load(
        (corpus / corpus_doc["flow"].removeprefix("./")).read_text())
    asks, ask_defaults = [], {}
    if "ask" in corpus_doc:
        ask_doc = yaml.safe_load((corpus / corpus_doc["ask"].removeprefix("./")).read_text())
        asks = [a["id"] for a in ask_doc["asks"]]
        # each ask's DECLARED retrieval defaults, so the ask screen follows the ask
        # (mirrors run_ask's own fallbacks: grounding 1.0, retrieve.mode hybrid)
        ask_defaults = {a["id"]: {"grounding": a.get("grounding", 1.0),
                                  "mode": a.get("retrieve", {}).get("mode", "hybrid")}
                        for a in ask_doc["asks"]}
    CatalogueApp(corpus, machine_root=corpus_root, declared=_declared_fields(flow),
                 asks=asks, ask_defaults=ask_defaults).run()
