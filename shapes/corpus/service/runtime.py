# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Writable runtime paths for a corpus's serve-side ephemeral state — the lock
files and the projection cache — kept OUTSIDE the corpus, so a read-only corpus
mount stays a pure artifact the sync can swap wholesale with nothing of the
serve's living inside it. Keyed by the corpus's resolved identity: two processes
on the SAME corpus share state, while different corpora never collide. The state
is rebuildable, so a fresh (ephemeral) runtime dir on each start is correct."""
import hashlib
import os
import tempfile
from pathlib import Path


def runtime_dir() -> Path:
    """The writable base for serve-side runtime files — never inside a corpus.
    Honors MOUI_RUNTIME_DIR, then MOUI_LOCK_DIR (back-compat), then
    XDG_RUNTIME_DIR, then the OS temp dir."""
    base = os.environ.get("MOUI_RUNTIME_DIR") or os.environ.get("MOUI_LOCK_DIR")
    if base:
        d = Path(base)
    elif os.environ.get("XDG_RUNTIME_DIR"):
        d = Path(os.environ["XDG_RUNTIME_DIR"]) / "moui"
    else:
        d = Path(tempfile.gettempdir()) / "moui-locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def corpus_path(corpus: Path, name: str) -> Path:
    """A runtime path for one corpus's named state file, OUTSIDE the corpus and
    keyed by its resolved identity — so the same corpus contends/shares while the
    corpus itself stays an untouched read-only artifact."""
    key = hashlib.sha256(str(Path(corpus).resolve()).encode()).hexdigest()[:16]
    return runtime_dir() / f"corpus-{key}.{name}"
