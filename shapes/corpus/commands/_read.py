# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared resolution and folding for the read commands. Read-only by design:
nothing in commands/ imports sidecar.write or sidecar.append."""
import sys
from pathlib import Path

from shapes.corpus.engine import identity, sidecar
from shapes.corpus.engine.errors import ContractError
from shapes.corpus.engine.fold import fold


def resolve_corpus(args: list) -> Path:
    if not args:
        print("usage: mo corpus <cmd> <path> [...]", file=sys.stderr)
        sys.exit(1)
    corpus = Path(args[0]).resolve()
    if not corpus.exists():
        raise ContractError(f"corpus path is missing or a dangling symlink: {corpus}")
    if not (corpus / "corpus.yaml").is_file():
        print(f"not a corpus (no corpus.yaml): {corpus}", file=sys.stderr)
        sys.exit(1)
    return corpus


def load(meta_path: Path) -> tuple[dict, dict]:
    """(sidecar doc, projection) for one pair."""
    doc = sidecar.read(meta_path)
    return doc, fold(doc.get("stages", []))


def area_of(corpus_dir: Path, meta_path: Path) -> str:
    """'working/datasheet', 'failed/inbox', 'corpus', ... from location."""
    rel = meta_path.parent.relative_to(corpus_dir)
    return "/".join(rel.parts[:-1]) if len(rel.parts) > 1 else rel.parts[0]