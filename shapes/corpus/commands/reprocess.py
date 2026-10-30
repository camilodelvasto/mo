# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus reprocess <path> (<doc_id…> | --all) [--from <stage>] [-v|-vv] —
re-run documents under the current flow. Targets are explicit doc ids; --all
sweeps every document and must be spelled out — a rewind of the whole corpus
is never the default. --from <stage> rewinds to that stage, reusing earlier
artifacts; omitted re-runs from the original. One-shot: acquires the engine
lock (refusing if a watcher holds it), rewinds the targets, runs them to
completion, and exits."""
import sys
from pathlib import Path

from shapes.corpus.commands._read import resolve_corpus
from shapes.corpus.engine.errors import CorpusError
from shapes.corpus.engine.reactor import Engine


def run(corpus_root: Path, instance: str, args: list) -> None:
    from shapes.corpus.engine.observer import ConsoleObserver
    from shapes.corpus.service import locks

    from_stage = None
    level = 0
    all_docs = False
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--from":
            if i + 1 >= len(args):
                print("--from needs a stage name", file=sys.stderr)
                sys.exit(1)
            from_stage = args[i + 1]
            i += 2
            continue
        if a == "--all":
            all_docs = True
        elif a in ("-v", "--verbose"):
            level = max(level, 1)
        elif a == "-vv":
            level = 2
        elif a.startswith("-"):
            print(f"unknown flag: {a}", file=sys.stderr)
            sys.exit(1)
        else:
            positional.append(a)
        i += 1

    doc_ids = positional[1:]
    if all_docs and doc_ids:
        print("--all and doc ids are contradictory — name the docs or sweep "
              "everything, not both", file=sys.stderr)
        sys.exit(1)
    if not all_docs and not doc_ids:
        print("reprocess needs explicit doc ids, or --all to rewind EVERY "
              "document under the flow", file=sys.stderr)
        sys.exit(1)

    corpus = resolve_corpus(positional)

    lock = locks.lock_path(corpus, "engine.lock")
    try:
        locks.acquire(lock, {"role": "reprocess"})
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    try:
        engine = Engine(corpus, corpus_root, observer=ConsoleObserver(level),
                        resume=False)
        done = engine.reprocess(doc_ids or None, from_stage)
        engine.drain()
        print(f"reprocessed {done} document(s)")
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    finally:
        locks.release(lock)
