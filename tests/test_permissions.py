"""Tests for runtime permission enforcement."""
import subprocess
import sys
from pathlib import Path

CORPUS_ROOT = str(Path(__file__).parent.parent)


def test_enforce_network_none_blocks_remote_connections():
    """When network is 'none', connecting to a remote host raises PermissionError."""
    code = """
import socket
from cli.permissions import enforce_network
enforce_network("none")
try:
    socket.create_connection(("1.2.3.4", 80), timeout=0.1)
    print("CONNECTED")
except PermissionError as e:
    print(f"BLOCKED:{e}")
except Exception as e:
    print(f"OTHER:{e}")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=10,
        cwd=CORPUS_ROOT,
    )
    assert "BLOCKED:" in result.stdout, f"Expected BLOCKED, got: {result.stdout}{result.stderr}"


def test_enforce_network_none_allows_localhost():
    """Even with network 'none', localhost connections are not blocked."""
    code = """
import socket
from cli.permissions import enforce_network
enforce_network("none")
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.1)
try:
    s.connect(("127.0.0.1", 1))
    print("CONNECTED")
except PermissionError:
    print("BLOCKED")
except (ConnectionRefusedError, OSError):
    print("ALLOWED")
finally:
    s.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=10,
        cwd=CORPUS_ROOT,
    )
    assert "ALLOWED" in result.stdout, f"Expected ALLOWED, got: {result.stdout}{result.stderr}"


def test_enforce_network_unrestricted_does_not_block():
    """When network is 'unrestricted', nothing is blocked."""
    code = """
import socket
from cli.permissions import enforce_network
enforce_network("unrestricted")
print(f"NAME:{socket.create_connection.__name__}")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=10,
        cwd=CORPUS_ROOT,
    )
    assert "NAME:create_connection" in result.stdout
