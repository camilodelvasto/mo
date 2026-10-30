# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""LiveTail: a bounded, self-erasing activity viewport. Milestones persist;
activity renders in the last-N window and vanishes when the step ends."""
import io

from cli.ui.livetail import LiveTail


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_renders_at_most_window_lines():
    out = _Tty()
    t = LiveTail(out, window=3, width=80)
    for i in range(6):
        t.add(f"line{i}")
    # the final frame (after the last cursor-up) holds only the newest 3
    final = out.getvalue().rsplit("\x1b[3F", 1)[-1]
    assert "line3" in final and "line5" in final
    assert "line0" not in final


def test_close_erases_the_window():
    out = _Tty()
    t = LiveTail(out, window=3, width=80)
    t.add("a")
    t.add("b")
    t.close()
    # cursor up over the 2 rendered lines, then erase to end of screen
    assert out.getvalue().endswith("\x1b[2F\x1b[0J")


def test_close_with_nothing_rendered_writes_nothing():
    out = _Tty()
    LiveTail(out, window=3, width=80).close()
    assert out.getvalue() == ""


def test_truncates_to_width():
    out = _Tty()
    t = LiveTail(out, window=2, width=20)
    t.add("x" * 100)
    assert "x" * 100 not in out.getvalue()


def test_non_tty_is_plain_prefixed_passthrough():
    out = io.StringIO()                       # isatty() → False
    t = LiveTail(out, window=3, width=80)
    t.add("hello")
    t.add("world")
    t.close()
    body = out.getvalue()
    assert "\x1b[" not in body                # zero escapes
    assert "    hello\n" in body and "    world\n" in body
