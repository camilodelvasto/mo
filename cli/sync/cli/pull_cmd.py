"""mo sync pull [folder] — pull from remote."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from cli.sync.client import SyncClient
from cli.sync.errors import MouiSyncError


def run(corpus_root: Path, args: list):
    folder = None
    if args:
        from cli.sync.cli.resolve import resolve_folder
        try:
            folder = str(resolve_folder(args))
        except MouiSyncError as exc:
            print(str(exc))
            sys.exit(1)

    async def _pull():
        client = SyncClient()
        await client.connect()
        try:
            return await client.pull(folder)
        finally:
            await client.close()

    try:
        result = asyncio.run(_pull())
    except (ConnectionRefusedError, FileNotFoundError):
        print("Cannot reach daemon. Is it running? Try: mo sync daemon start")
        sys.exit(1)

    for entry in result:
        name = Path(entry["folder"]).name
        if entry["ok"]:
            print(f"  pulled {name}")
        else:
            print(f"  failed {name}: {entry['error']}")
            sys.exit(1)
