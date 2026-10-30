"""mo sync status — show per-folder sync state."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from cli.sync.client import SyncClient


def run(corpus_root: Path, args: list):
    async def _status():
        client = SyncClient()
        await client.connect()
        try:
            return await client.status()
        finally:
            await client.close()

    try:
        status = asyncio.run(_status())
    except (ConnectionRefusedError, FileNotFoundError):
        print("DAEMON   not running")
        sys.exit(1)

    print("DAEMON   running")
    print()

    if not status:
        print("No folders tracked. Use 'mo sync init <folder>' to start.")
        return

    for folder_path, state in status.items():
        folder_name = Path(folder_path).name
        s = state["state"]
        indicator = "●" if s == "clean" else "◌"
        print(f"  {indicator}  {folder_name:<24} {s}")
