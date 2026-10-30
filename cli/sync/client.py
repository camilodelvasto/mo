"""JSON-RPC client for the moui sync daemon.

This is the cross-shape integration surface. Only legal import
from outside sync code.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cli.sync.daemon.server import default_socket_path


class SyncClient:
    def __init__(self, socket_path: Path | None = None) -> None:
        self._socket_path = socket_path or default_socket_path()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._req_id = 0

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(
            str(self._socket_path)
        )

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None

    async def _call(self, method: str, params: dict | None = None) -> dict:
        if self._writer is None or self._reader is None:
            raise RuntimeError("not connected — call connect() first")

        self._req_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        self._writer.write(json.dumps(request).encode() + b"\n")
        await self._writer.drain()

        line = await self._reader.readline()
        if not line:
            raise ConnectionError("daemon closed the connection")

        response = json.loads(line)
        if "error" in response:
            raise RuntimeError(
                f"RPC error {response['error'].get('code')}: "
                f"{response['error'].get('message')}"
            )
        return response["result"]

    async def ping(self) -> dict:
        return await self._call("ping")

    async def status(self) -> dict:
        return await self._call("status")

    async def push(self, folder: str | None = None) -> list:
        params = {"folder": folder} if folder else None
        return await self._call("push", params)

    async def pull(self, folder: str | None = None) -> list:
        params = {"folder": folder} if folder else None
        return await self._call("pull", params)

    async def rescan(self) -> dict:
        return await self._call("rescan")

    async def recipients_list(self, folder: str) -> list[str]:
        return await self._call("recipients.list", {"folder": folder})

    async def recipients_add(self, folder: str, pubkey: str) -> dict:
        return await self._call("recipients.add", {"folder": folder, "pubkey": pubkey})

    async def recipients_remove(self, folder: str, pubkey: str) -> dict:
        return await self._call("recipients.remove", {"folder": folder, "pubkey": pubkey})

    def is_available(self) -> bool:
        return self._socket_path.exists()
