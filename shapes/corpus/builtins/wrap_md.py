# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""engine.wrap-md — plain text becomes a markdown transcript."""
from pathlib import Path

from shapes.corpus.engine.errors import StageFailure


def run(pair_dir: Path, stage: dict, input_path: Path) -> dict:
    try:
        text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise StageFailure(stage["id"], f"not text: {exc}") from exc
    out = pair_dir / "transcript.md"
    out.write_text(text if text.endswith("\n") else text + "\n")
    return {"fields": {}, "output": out, "meters": {}}
