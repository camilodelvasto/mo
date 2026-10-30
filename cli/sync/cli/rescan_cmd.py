"""mo sync rescan — trigger a rescan of sync declarations."""

import asyncio
import sys
from pathlib import Path

from cli.sync.client import SyncClient


async def _run(corpus_root: Path, args: list):
    client = SyncClient()
    if not client.is_available():
        print("sync: offline (daemon not running)")
        sys.exit(1)

    await client.connect()
    try:
        result = await client.rescan()
        if result.get("ok"):
            print("sync: rescan triggered")
        else:
            print("sync: rescan failed")
            sys.exit(1)
    finally:
        await client.close()


def run(corpus_root: Path, args: list):
    asyncio.run(_run(corpus_root, args))
