# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus find <path> "question" [--where EXPR] — bare retrieval, no LLM."""
from pathlib import Path

from shapes.corpus.access import run_ask
from shapes.corpus.commands._read import resolve_corpus
from shapes.corpus.commands._access_cli import parse_query_args, print_passages


def run(corpus_root: Path, instance: str, args: list) -> None:
    corpus = resolve_corpus(args)
    question, opts = parse_query_args(args[1:])
    if "grounding" in opts:
        raise SystemExit("--grounding applies only to 'mo corpus ask' (find does no synthesis)")
    if "history" in opts:
        raise SystemExit("--history applies only to 'mo corpus ask' (find does no condensation)")
    record = run_ask.run_ask(corpus, corpus_root, "find", question,
                             where=opts.get("where"), mode=opts.get("mode"),
                             k=opts.get("k"))
    print_passages(record["passages"])
