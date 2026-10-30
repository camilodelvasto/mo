"""mo sync recipients <folder> list|add|remove [pubkey] — manage folder recipients."""

import asyncio
import sys
from pathlib import Path

from cli.sync.client import SyncClient

USAGE = "Usage: mo sync recipients <folder> list|add|remove [pubkey]"


async def _run(corpus_root: Path, args: list):
    if len(args) < 2:
        print(USAGE)
        sys.exit(1)

    folder = args[0]
    action = args[1]

    client = SyncClient()
    if not client.is_available():
        print("sync: offline (daemon not running)")
        sys.exit(1)

    await client.connect()
    try:
        if action == "list":
            recipients = await client.recipients_list(folder)
            if not recipients:
                print(f"  {folder}: no recipients")
            else:
                print(f"  {folder} recipients:")
                for r in recipients:
                    print(f"    {r}")

        elif action == "add":
            if len(args) < 3:
                print("Usage: mo sync recipients <folder> add <pubkey>")
                sys.exit(1)
            pubkey = args[2]
            result = await client.recipients_add(folder, pubkey)
            print(f"  added to {folder}: {pubkey}")

        elif action == "remove":
            if len(args) < 3:
                print("Usage: mo sync recipients <folder> remove <pubkey>")
                sys.exit(1)
            pubkey = args[2]
            result = await client.recipients_remove(folder, pubkey)
            print(f"  removed from {folder}: {pubkey}")

        else:
            print(f"Unknown recipients action: {action}")
            print(USAGE)
            sys.exit(1)
    finally:
        await client.close()


def run(corpus_root: Path, args: list):
    asyncio.run(_run(corpus_root, args))
