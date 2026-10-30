# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapter: mo sheets rebuild <sheet>"""
import sys
from pathlib import Path


def run(corpus_root: Path, instance: str, args: list) -> None:
    if not args:
        print("Usage: mo sheets rebuild <sheet>")
        sys.exit(1)

    from shapes.sheets.src.cli_utils import resolve_sheet
    from shapes.sheets.src.rebuild import rebuild_state

    sheet_dir = resolve_sheet(args[0], corpus_root)
    rebuild_state(sheet_dir)
    print(f"Rebuilt state.sqlite for {sheet_dir.name}")
