"""Asyncio Unix socket server for moui sync daemon JSON-RPC."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from cli.sync.daemon.rpc import PROTOCOL_VERSION, RPCDispatcher


def default_socket_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "moui" / "sync.sock"
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "moui-sync.sock"
    return Path(f"/run/user/{os.getuid()}/moui-sync.sock")


class RPCServer:
    def __init__(
        self,
        dispatcher: RPCDispatcher,
        socket_path: Path | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._socket_path = socket_path or default_socket_path()
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self._socket_path.exists():
            self._socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self._socket_path),
        )
        os.chmod(self._socket_path, 0o600)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._socket_path.exists():
            self._socket_path.unlink()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                        "version": PROTOCOL_VERSION,
                    }
                else:
                    response = await self._dispatcher.dispatch(request)
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()
        finally:
            writer.close()
