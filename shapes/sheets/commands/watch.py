# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapter: mo sheets watch <sheet>"""
import sys
from pathlib import Path


def run(corpus_root: Path, instance: str, args: list) -> None:
    if not args:
        print("Usage: mo sheets watch <sheet>")
        sys.exit(1)

    from shapes.sheets.src.cli_utils import resolve_sheet
    from shapes.sheets.src.watcher import watch_inbox

    sheet_dir = resolve_sheet(args[0], corpus_root)
    print(f"Watching inbox for {sheet_dir.name}...")
    watch_inbox(sheet_dir, corpus_root=corpus_root)
