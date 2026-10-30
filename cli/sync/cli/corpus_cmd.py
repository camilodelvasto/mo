# cli/sync/cli/corpus_cmd.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo sync corpus <target> <env> — ship a corpus to its box and cut over."""
import sys
from datetime import datetime
from pathlib import Path
from cli.sync.corpus import sync

def run(corpus_root: Path, args: list) -> None:
    if len(args) < 2:
        print("Usage: mo sync corpus <target> <env>", file=sys.stderr); sys.exit(1)
    now = datetime.now().strftime("%Y%m%d-%H%M%S")
    sync.run(corpus_root, args[0], args[1], now=now)
