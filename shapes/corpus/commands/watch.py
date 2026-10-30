# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus watch <path> [--restart] [-v|-vv] — start the engine over one corpus. -v streams pipeline activity; -vv also prints LLM prompts and responses."""
import sys
from pathlib import Path

from shapes.corpus.commands._read import resolve_corpus
from shapes.corpus.engine.errors import CorpusError
from shapes.corpus.engine.reactor import Engine


def run(corpus_root: Path, instance: str, args: list) -> None:
    from shapes.corpus.engine.observer import ConsoleObserver
    restart = "--restart" in args
    level = 0
    for a in args:
        if a in ("-v", "--verbose"):
            level = max(level, 1)
        elif a == "-vv":
            level = 2
    known = {"--restart", "-v", "-vv", "--verbose"}
    unknown = [a for a in args if a.startswith("-") and a not in known]
    if unknown:
        print(f"unknown flag(s): {' '.join(unknown)}", file=sys.stderr)
        sys.exit(1)
    try:
        corpus = resolve_corpus([a for a in args if not a.startswith("-")])
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    from shapes.corpus.service import locks
    lock = locks.lock_path(corpus, "engine.lock")
    try:
        locks.acquire(lock, {"role": "engine"})
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    try:
        engine = Engine(corpus, corpus_root, observer=ConsoleObserver(level))
    except CorpusError as exc:
        locks.release(lock)
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"watching {corpus} (flow {engine.flow['id']} "
          f"v{engine.flow['version']}, pool {engine.pool_size})")
    try:
        if restart:
            engine.restart_failed()   # inside the try: a raise here must not leak the lock
        engine.run()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        locks.release(lock)
