# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Maintain a corpus volume's versioned-dir + current/previous symlinks. stdlib
only, so the SAME code runs in tests (locally) and on the box (`ssh … python3 -
<op> <vol> <args>`, this file piped on stdin). No portable atomic two-symlink
swap exists, so the invariant comes from ordering (previous before current) +
per-link atomic replace: os.symlink to a tmp name, then os.replace (rename(2))
over the link — which replaces the symlink itself, never follows it into the
target dir. No fallbacks."""
import os
import shutil
import sys
from pathlib import Path


def _atomic_symlink(target: str, link: Path) -> None:
    tmp = link.with_name(f".{link.name}.tmp.{os.getpid()}")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(target, tmp)
    os.replace(tmp, link)        # atomic rename; replaces the symlink, doesn't follow it


def scaffold(volume: Path) -> None:
    (volume / "versions").mkdir(parents=True, exist_ok=True)


def flip(volume: Path, version: str) -> None:
    cur = volume / "current"
    if cur.is_symlink():
        _atomic_symlink(os.readlink(cur), volume / "previous")   # previous FIRST
    _atomic_symlink(f"versions/{version}", cur)                  # then current


def rollback(volume: Path) -> None:
    prev = volume / "previous"
    if not prev.is_symlink():
        raise SystemExit("no previous to roll back to")
    _atomic_symlink(os.readlink(prev), volume / "current")


def prune(volume: Path, keep: int) -> None:
    vers = volume / "versions"
    protected = set()
    for link in ("current", "previous"):
        p = volume / link
        if p.is_symlink():
            protected.add(os.path.basename(os.readlink(p)))
    dirs = sorted((d for d in vers.iterdir() if d.is_dir() and d.name not in protected),
                  key=lambda d: d.stat().st_mtime)              # oldest first
    doomed = dirs[:-keep] if keep else dirs
    for d in doomed:
        shutil.rmtree(d)


if __name__ == "__main__":
    op, vol, *rest = sys.argv[1:]
    {"scaffold": lambda: scaffold(Path(vol)),
     "flip": lambda: flip(Path(vol), rest[0]),
     "rollback": lambda: rollback(Path(vol)),
     "prune": lambda: prune(Path(vol), int(rest[0]))}[op]()
