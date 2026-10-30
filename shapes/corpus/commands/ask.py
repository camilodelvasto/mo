# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus ask <path> <ask> "question" [--where EXPR] [--mode M] [--k N]
[--grounding G] [--history JSON|@file] [--json]."""
import json
from pathlib import Path

from shapes.corpus.access import run_ask
from shapes.corpus.access.errors import AccessError
from shapes.corpus.engine.errors import CapabilityError
from shapes.corpus.commands._read import resolve_corpus
from shapes.corpus.commands._access_cli import parse_query_args, print_answer, error_kind


def run(corpus_root: Path, instance: str, args: list) -> None:
    corpus = resolve_corpus(args)
    ask_id = args[1]
    question, opts = parse_query_args(args[2:])
    if opts.get("stream"):
        import sys
        for event in run_ask.run_ask_stream(
                corpus, corpus_root, ask_id, question,
                where=opts.get("where"), mode=opts.get("mode"),
                k=opts.get("k"), grounding=opts.get("grounding"),
                history=opts.get("history"), attachments=opts.get("attachments")):
            sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            if event.get("event") == "error":
                raise SystemExit(1)
        return
    try:
        record = run_ask.run_ask(corpus, corpus_root, ask_id, question,
                                 where=opts.get("where"), mode=opts.get("mode"),
                                 k=opts.get("k"), grounding=opts.get("grounding"),
                                 history=opts.get("history"),
                                 attachments=opts.get("attachments"))
    except (AccessError, CapabilityError) as exc:  # every engine error → a typed envelope under --json
        if opts.get("json"):
            print(json.dumps({"error": {"kind": error_kind(exc), "detail": str(exc)}},
                             ensure_ascii=False))
            raise SystemExit(1)
        raise SystemExit(str(exc))
    if opts.get("json"):
        print(json.dumps(record, ensure_ascii=False))
    else:
        print_answer(record)
