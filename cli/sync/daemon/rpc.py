"""JSON-RPC 2.0 dispatcher for moui sync daemon."""

from __future__ import annotations

from typing import Any, Callable, Coroutine

PROTOCOL_VERSION = 1


class RPCDispatcher:
    def __init__(self) -> None:
        self._methods: dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {}

    def method(self, name: str):
        """Decorator to register a handler coroutine."""
        def decorator(fn):
            self._methods[name] = fn
            return fn
        return decorator

    async def dispatch(self, request: dict) -> dict:
        req_id = request.get("id")

        if "jsonrpc" not in request or "method" not in request:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request"},
                "version": PROTOCOL_VERSION,
            }

        method_name = request["method"]
        handler = self._methods.get(method_name)

        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method_name}"},
                "version": PROTOCOL_VERSION,
            }

        params = request.get("params")
        try:
            result = await handler(params)
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
                "version": PROTOCOL_VERSION,
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
            "version": PROTOCOL_VERSION,
        }
