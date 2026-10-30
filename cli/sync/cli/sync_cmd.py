"""mo sync <folder> — force sync one folder now (commit + push)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from cli.sync.client import SyncClient
from cli.sync.cli.resolve import resolve_folder
from cli.sync.errors import MouiSyncError


def run(corpus_root: Path, args: list):
    """Force sync a specific folder via the daemon."""
    if not args:
        print("Usage: mo sync <folder>")
        sys.exit(1)

    try:
        folder_path = resolve_folder(args)
    except MouiSyncError as exc:
        print(str(exc))
        sys.exit(1)

    async def _push():
        client = SyncClient()
        await client.connect()
        try:
            return await client.push(str(folder_path))
        finally:
            await client.close()

    try:
        results = asyncio.run(_push())
    except (ConnectionRefusedError, FileNotFoundError):
        print("Cannot reach daemon. Is it running? Try: mo sync daemon start")
        sys.exit(1)

    for r in results:
        if r["ok"]:
            print(f"Synced: {Path(r['folder']).name}")
        else:
            print(f"Sync failed for {Path(r['folder']).name}: {r['error']}")
            sys.exit(1)
