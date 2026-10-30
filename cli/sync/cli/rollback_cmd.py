# cli/sync/cli/rollback_cmd.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo sync rollback <target> <env> — flip-back to prior version."""
import sys
from pathlib import Path
from cli.sync.corpus import sync

def run(corpus_root: Path, args: list) -> None:
    if len(args) < 2:
        print("Usage: mo sync rollback <target> <env>", file=sys.stderr); sys.exit(1)
    sync.rollback(corpus_root, args[0], args[1])
