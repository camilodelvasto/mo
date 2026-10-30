# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Reveal a file in the host OS file manager — a small platform capability behind
a contract, not inlined into the app. The service hands the renderer an absolute
path (it owns storage); this opens the OS file manager at that file. Pluggable
runner/platform so each platform's command is testable without spawning it."""
import subprocess
import sys
from pathlib import Path


def reveal(path: str, *, runner=subprocess.run, platform: str = sys.platform) -> list:
    """Reveal `path` in the OS file manager; returns the command issued.

    macOS reveals the file in Finder (`open -R`); Windows selects it in Explorer;
    Linux has no portable 'select', so it opens the containing folder."""
    if platform == "darwin":
        cmd = ["open", "-R", path]
    elif platform.startswith("win"):
        cmd = ["explorer", f"/select,{path}"]
    else:
        cmd = ["xdg-open", str(Path(path).parent)]
    runner(cmd, check=False)
    return cmd
