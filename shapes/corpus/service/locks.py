# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Corpus lock files. engine.lock (the watch process) and service.lock (the
serve process) each record {pid, host, started, …}. Reclaim is by liveness
ONLY — no timeout that guesses, no silent overwrite:

  - a dead PID on THIS host is stale: acquire, with a logged note;
  - a live PID refuses;
  - a lock from ANOTHER host is unverifiable and refuses, naming itself.
"""
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

from shapes.corpus.engine.errors import LockError
from shapes.corpus.service import runtime

HOST = socket.gethostname()


def lock_path(corpus: Path, name: str) -> Path:
    """The runtime path for a corpus's lock — OUTSIDE the corpus, so the serve
    never writes the data it serves (the read-only mount enforces that line).
    Keyed by the corpus's resolved identity, so two processes on the SAME corpus
    still contend, while the corpus stays an artifact the sync can swap wholesale
    with nothing of the serve's living inside it."""
    return runtime.corpus_path(corpus, name)


def _write(lock_path: Path, data: dict) -> None:
    tmp = lock_path.parent / f".{lock_path.name}.tmp"
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, lock_path)


def read(lock_path: Path) -> dict | None:
    if not lock_path.is_file():
        return None
    try:
        return json.loads(lock_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, owned by someone else
    return True


def alive(lock_path: Path) -> bool:
    """True if the lock is held by a process we can verify is running on this
    host. A lock from another host is reported live (we cannot disprove it)."""
    data = read(lock_path)
    if not data:
        return False
    if data.get("host") != HOST:
        return True
    return _pid_alive(int(data.get("pid", -1)))


def acquire(lock_path: Path, extra: dict) -> None:
    existing = read(lock_path)
    if existing is not None:
        if existing.get("host") != HOST:
            raise LockError(
                f"{lock_path.name} held by another host "
                f"({existing.get('host')!r}, pid {existing.get('pid')}); "
                "unverifiable from here — resolve it by hand")
        if _pid_alive(int(existing.get("pid", -1))):
            raise LockError(
                f"{lock_path.name} held by live pid {existing.get('pid')} "
                "on this host — another instance is already running")
        print(f"reclaiming stale {lock_path.name} "
              f"(pid {existing.get('pid')} is gone)", file=sys.stderr)
    data = {"pid": os.getpid(), "host": HOST,
            "started": datetime.now(timezone.utc).isoformat(), **extra}
    _write(lock_path, data)


def release(lock_path: Path) -> None:
    """Drop our own lock. A lock owned by another pid/host is left alone."""
    data = read(lock_path)
    if data and data.get("pid") == os.getpid() and data.get("host") == HOST:
        lock_path.unlink(missing_ok=True)
