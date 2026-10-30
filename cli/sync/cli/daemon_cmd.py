"""mo sync daemon start|stop|restart|status — manage the sync daemon process."""

import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

from cli.sync.cli.resolve import resolve_infrastructure
from cli.sync.errors import MouiSyncError

USAGE = "Usage: mo sync daemon start|stop|restart|status"


def _config_dir() -> Path:
    """Per-user config directory for sync state."""
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "moui" / "sync"
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / "moui" / "sync"


def _read_pid() -> int | None:
    pid_file = _config_dir() / "pid"
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return pid
    except ValueError:
        return None
    except ProcessLookupError:
        return None


def _wait_for_exit(pid: int, timeout_seconds: float = 5.0) -> None:
    """Wait for a process to exit. Raises if it doesn't within timeout."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            return
    raise RuntimeError(f"process {pid} did not exit within {timeout_seconds}s")


def _start(infrastructure_path: Path):
    existing = _read_pid()
    if existing is not None:
        print(f"sync daemon already running (pid {existing})")
        sys.exit(1)

    config_dir = _config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    log_path = config_dir / "daemon.log"

    log_file = open(log_path, "a")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m", "cli.sync.daemon.main",
            "daemon",
            "--infrastructure", str(infrastructure_path),
        ],
        start_new_session=True,
        stdout=log_file,
        stderr=log_file,
    )
    print(f"sync daemon started (pid {proc.pid})")
    print(f"  logs: {log_path}")


def _stop():
    pid = _read_pid()
    if pid is None:
        print("sync daemon not running")
        sys.exit(0)

    os.kill(pid, signal.SIGTERM)
    _wait_for_exit(pid)
    print(f"sync daemon stopped (pid {pid})")


def _status():
    pid = _read_pid()
    if pid is None:
        print("sync daemon: not running")
    else:
        print(f"sync daemon: running (pid {pid})")


def run(corpus_root: Path, args: list):
    if not args:
        print(USAGE)
        sys.exit(1)

    action = args[0]

    if action in ("start", "restart"):
        try:
            infrastructure_path = resolve_infrastructure(args)
        except MouiSyncError as exc:
            print(str(exc))
            sys.exit(1)

        if action == "restart":
            pid = _read_pid()
            if pid is not None:
                os.kill(pid, signal.SIGTERM)
                _wait_for_exit(pid)
                print(f"sync daemon stopped (pid {pid})")

        _start(infrastructure_path)

    elif action == "stop":
        _stop()
    elif action == "status":
        _status()
    else:
        print(f"Unknown daemon action: {action}")
        print(USAGE)
        sys.exit(1)
