# cli/sync/corpus/snapshot.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Build a corpus snapshot (data only, runtime excluded by construction) and
content-address it. The digest is a merkle over sorted (relpath, file-hash)
pairs — independent of how the snapshot is packed for transport — so an
unchanged corpus produces the same id (idempotent) and the same value gates a
torn transfer on the box."""
import hashlib
import shutil
from pathlib import Path

# Exactly what a corpus snapshot IS. Everything else (derived/, locks, inbox/
# working/failed/quarantine/retired/dropbox) is runtime or staging, never data.
_TOP_FILES = ("corpus.yaml", "flow.yaml", "ask.yaml")
_TOP_DIRS = ("corpus", "index")


def build_snapshot(corpus_dir: Path, dest: Path) -> None:
    corpus_yaml = corpus_dir / "corpus.yaml"
    if not corpus_yaml.is_file():
        raise FileNotFoundError(f"not a corpus: missing corpus.yaml in {corpus_dir}")
    dest.mkdir(parents=True, exist_ok=True)
    for name in _TOP_FILES:
        src = corpus_dir / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    for name in _TOP_DIRS:
        src = corpus_dir / name
        if src.is_dir():
            # Drop macOS cruft so the snapshot is canonical regardless of the
            # authoring machine — .DS_Store/._* are never corpus data.
            shutil.copytree(src, dest / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(".DS_Store", "._*"))


def canonical_digest(root: Path) -> str:
    # Sort by the POSIX relpath STRING (code-point order). For UTF-8 names this
    # equals `LC_ALL=C sort` byte order on the box (UTF-8 preserves code-point
    # order), so the box-side recompute (Task 5) agrees on non-ASCII filenames.
    files = sorted((p for p in root.rglob("*") if p.is_file()),
                   key=lambda p: p.relative_to(root).as_posix())
    lines = []
    for p in files:
        rel = p.relative_to(root).as_posix()
        lines.append(f"{rel}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n")
    # Trailing newline PER entry — the box pipeline emits one per line, so the
    # bytes hashed must match exactly. Proven by the cross-check test in Task 5.
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def version_id(digest: str, *, now: str) -> str:
    return f"{now}-{digest[:16]}"


if __name__ == "__main__":
    # Box-side recompute: `ssh … python3 - <dir>` (this file on stdin) prints the
    # digest, so the box uses the IDENTICAL algorithm — no shell-vs-Python framing
    # or locale-sort divergence possible (Task 5 validate_digest).
    import sys
    print(canonical_digest(Path(sys.argv[1])))
