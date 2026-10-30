# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The display-label seam. The renderer paints facet keys and status values;
their human labels live in an optional per-corpus language.yaml (the same idea
as grove's language file), so translating or renaming is a file edit, never an
app change. No file, or no entry: the key renders verbatim — never a guess."""
from pathlib import Path

import yaml


def load(corpus_dir: Path) -> dict:
    """The corpus's label map, or {} when there is no language.yaml."""
    path = corpus_dir / "language.yaml"
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    return doc.get("labels", {}) or {}


def label(label_map: dict, key: str) -> str:
    """The display label for a key — its mapping, or the key verbatim."""
    return label_map.get(key, key)
