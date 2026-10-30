# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapter: mo sheets ingest <sheet> <source|->"""
import sys
from datetime import datetime, timezone
from pathlib import Path


def run(corpus_root: Path, instance: str, args: list) -> None:
    if len(args) < 2:
        print("Usage: mo sheets ingest <sheet> <source|->")
        print("Use - for stdin")
        sys.exit(1)

    from shapes.sheets.src.cli_utils import resolve_sheet

    sheet_dir = resolve_sheet(args[0], corpus_root)
    source = args[1]

    staging = sheet_dir / "ingest" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    inbox = sheet_dir / "ingest" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    if source == "-":
        content = sys.stdin.read()
    else:
        content = source

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
    filename = f"{ts}-from-cli.txt"
    tmp = staging / filename
    tmp.write_text(content)

    import shutil
    shutil.move(str(tmp), str(inbox / filename))
    print(f"Written to {inbox / filename}")
