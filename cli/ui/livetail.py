# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""A bounded, self-erasing activity viewport for long-running steps.

The deploy's output contract has two kinds of lines: MILESTONES (the
persistent narrative, printed by orchestrators) and ACTIVITY (a remote
command's own output — evidence the step is alive). LiveTail renders
activity as the last `window` lines, dimmed and indented, overwritten in
place; close() erases the region so scrollback keeps only milestones.

Not a TTY → plain prefixed passthrough, zero escape codes: logs and CI
get the full text. ANSI only — cursor-up (CSI nF), erase-line (CSI 2K),
erase-below (CSI 0J). No curses, no alternate screen."""
import shutil
from collections import deque

_PREFIX = "    "
_DIM, _RESET = "\x1b[2m", "\x1b[0m"


class LiveTail:
    def __init__(self, stream, window: int = 5, width: int | None = None):
        self._stream = stream
        self._tty = stream.isatty()
        self._window = deque(maxlen=window)
        self._width = width
        self._rendered = 0            # lines currently on screen

    def add(self, line: str) -> None:
        line = line.rstrip("\n")
        if not self._tty:
            self._stream.write(f"{_PREFIX}{line}\n")
            return
        self._window.append(line)
        self._redraw()

    def close(self) -> None:
        if not self._tty or self._rendered == 0:
            return
        self._stream.write(f"\x1b[{self._rendered}F\x1b[0J")
        self._stream.flush()
        self._rendered = 0

    def _redraw(self) -> None:
        width = self._width or shutil.get_terminal_size().columns
        room = max(1, width - len(_PREFIX) - 1)
        if self._rendered:
            self._stream.write(f"\x1b[{self._rendered}F")
        for line in self._window:
            self._stream.write(f"\x1b[2K{_PREFIX}{_DIM}{line[:room]}{_RESET}\n")
        self._stream.flush()
        self._rendered = len(self._window)
