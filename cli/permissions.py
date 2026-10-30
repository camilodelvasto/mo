"""Network guardrail for shape development.

When a shape declares permissions.network: 'none', this module patches
socket.create_connection to reject non-localhost connections. This catches
accidental network calls from honest code — urllib, requests, http.client,
and anything else that routes through socket.create_connection.

This is a guardrail, not a sandbox. It does not catch: subprocess calls
(curl, wget), ctypes to system sockets, libraries using socket.socket()
directly, or any code that spawns child processes. For defence against
malicious shapes, OS-level sandboxing is required.

Localhost (127.0.0.1, ::1, localhost) is always allowed — shapes need
it for local servers (renderer shell-web, PDF export via headless browser).
"""
import socket

_LOCALHOST = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}
_original_create_connection = socket.create_connection
_enforced = False


def _guarded_create_connection(address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else address
    if str(host) in _LOCALHOST:
        return _original_create_connection(address, *args, **kwargs)
    raise PermissionError(
        f"Shape network access denied: connection to {host} blocked. "
        f"This shape declares permissions.network: none"
    )


def enforce_network(level: str) -> None:
    """Apply network restrictions based on the declared permission level.

    Args:
        level: 'none' (block all non-localhost), 'local' (allow localhost only,
               same as none for now), or 'unrestricted' (no restrictions).
    """
    global _enforced
    if level in ("none", "local"):
        if not _enforced:
            socket.create_connection = _guarded_create_connection
            _enforced = True
    elif level == "unrestricted":
        pass
    else:
        raise ValueError(f"Unknown network permission level: {level!r}")
