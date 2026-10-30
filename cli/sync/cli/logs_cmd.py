"""mo sync logs [--follow] — view sync log."""

import json
import os
import platform
import sys
import time
from pathlib import Path


def _config_dir() -> Path:
    """Per-user config directory for sync state."""
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "moui" / "sync"
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / "moui" / "sync"


def _format_log_line(line: str) -> str:
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return line.rstrip()
    ts = entry.get("ts", "")[:19]
    event_type = entry.get("type", "?")
    folder = entry.get("folder", "")
    parts = [ts, event_type, folder]
    error = entry.get("error")
    if error:
        parts.append(f"error={error}")
    sha = entry.get("sha")
    if sha:
        parts.append(sha[:8])
    return "  ".join(parts)


def run(corpus_root: Path, args: list):
    log_path = _config_dir() / "sync.log"
    if not log_path.exists():
        print("sync: no log file found")
        sys.exit(0)

    follow = "--follow" in args

    if not follow:
        with open(log_path) as f:
            lines = f.readlines()
        for line in lines[-50:]:
            print(_format_log_line(line))
        return

    # --follow: tail -f style
    with open(log_path) as f:
        f.seek(0, 2)  # seek to end
        try:
            while True:
                line = f.readline()
                if line:
                    print(_format_log_line(line), flush=True)
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
