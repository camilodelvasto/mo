# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""engine.passthrough — the input already is the transcript."""
import shutil
from pathlib import Path


def run(pair_dir: Path, stage: dict, input_path: Path) -> dict:
    out = pair_dir / "transcript.md"
    if input_path.resolve() != out.resolve():
        shutil.copyfile(input_path, out)
    return {"fields": {}, "output": out, "meters": {}}
