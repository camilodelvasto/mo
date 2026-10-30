# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus serve <corpus> [--port N] — the localhost read service."""
import sys
from pathlib import Path

import uvicorn

from shapes.corpus.commands._read import resolve_corpus
from shapes.corpus.engine.errors import CorpusError

HOST = "127.0.0.1"          # localhost only; exposure beyond the machine is 021's job


def run(corpus_root: Path, instance: str, args: list) -> None:
    port = 8787
    if "--port" in args:
        i = args.index("--port")
        port = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    host = HOST
    if "--host" in args:
        i = args.index("--host"); host = args[i + 1]; args = args[:i] + args[i + 2:]
    origins: list = []
    while "--allow-origin" in args:
        i = args.index("--allow-origin")
        origins.append(args[i + 1])
        args = args[:i] + args[i + 2:]
    unknown = [a for a in args if a.startswith("--")]
    if unknown:
        print(f"unknown flag(s): {' '.join(unknown)}", file=sys.stderr)
        sys.exit(1)
    from shapes.corpus.service.app import create_app, create_not_ready_app
    try:
        corpus = resolve_corpus([a for a in args if not a.startswith("--")])
    except CorpusError as exc:
        # Hold, don't crash: a missing/unsynced corpus is a legible running state.
        print(f"{exc} — holding 'corpus not ready' until a corpus is synced", file=sys.stderr)
        uvicorn.run(create_not_ready_app(str(exc), allow_origins=origins),
                    host=host, port=port, log_level="warning")
        return
    try:
        app = create_app(corpus, machine_root=corpus_root, allow_origins=origins)
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    from shapes.corpus.service import locks
    lock = locks.lock_path(corpus, "service.lock")   # runtime dir, not the read-only corpus
    try:
        locks.acquire(lock, {"role": "service", "port": port})
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"serving {corpus} on http://{host}:{port}")
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        locks.release(lock)
