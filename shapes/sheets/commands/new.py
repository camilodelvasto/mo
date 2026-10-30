# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapter: mo sheets new <path>"""
import sys
from pathlib import Path


def run(corpus_root: Path, instance: str, args: list) -> None:
    if not args:
        print("Usage: mo sheets new <path>")
        sys.exit(1)

    from shapes.sheets.src.scaffold import scaffold_sheet

    target = corpus_root / args[0]
    scaffold_sheet(target, corpus_root)
