# tests/test_grove_chat_js_streaming.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path
SRC = Path("shapes/grove/renderer/core/components/chat.js").read_text()

def test_requests_ndjson_stream():
    assert "application/x-ndjson" in SRC
    assert "getReader" in SRC                 # reads the body as a stream

def test_dispatches_the_event_vocabulary():
    for kind in ("'step'", "'token'", "'sources'", "'title'", "'done'", "'error'"):
        assert kind in SRC, f"missing handler for {kind}"

def test_no_longer_awaits_whole_record_json():
    # the streaming path must not parse the whole answer from res.json()
    assert "renderAnswer(record)" not in SRC  # the blocking _fillAnswer path is gone

def test_no_terminal_event_guard():
    # If stream ends without a `done` or `error` event, treat as failure.
    # Persistence must be gated on having seen `done`.
    assert "seenDone" in SRC or "terminalSeen" in SRC or "sawDone" in SRC or "terminal" in SRC
    assert "chat_unavailable" in SRC          # rendered on the no-terminal-event path

def test_no_terminal_event_guard_precedes_persistence():
    # A stream ending without done/error must not write history/persist:
    # the seenDone (or equivalent) guard must appear before the history push.
    # This test verifies the ordering: if (!seenDone) { error path } must precede
    # active.history.push, so that unclosed streams never persist.
    import re
    # find the critical section: _readStream call followed by guard check
    section = re.search(
        r"await _readStream\(.*?\).*?if\s*\(\s*!seenDone\s*\).*?active\.history\.push",
        SRC,
        re.DOTALL
    )
    assert section, \
        "stream reading + terminal guard + history push sequence not found in expected order"


def test_renders_instructions_block():
    assert "_renderInstructions" in SRC
    assert "instructions_html" in SRC

def test_composer_is_textarea_with_enter_semantics():
    assert "createElement('textarea')" in SRC
    assert "shiftKey" in SRC and "'Enter'" in SRC
    assert "ICON_STOP" in SRC


def test_composer_is_declarative_single_source_of_truth():
    # The composer is DECLARATIVE: one source of truth `inflight` (the active turn or null),
    # and the view is a pure function of it (renderComposer). No flag soup / imperative modes.
    assert "let inflight" in SRC
    assert "renderComposer" in SRC
    # The button is trivial: active query → stop, idle → send. It never native-submits.
    import re
    click = re.search(r"send\.addEventListener\('click'.*?\}\);", SRC, re.DOTALL)
    assert click, "button click handler not found"
    assert "inflight" in click.group(0) and "stopTurn" in click.group(0), \
        "button click must route on inflight: active → stopTurn, idle → send"


def test_stop_undoes_the_turn_via_declarative_teardown():
    # Stop = undo the in-flight turn: null `inflight` FIRST, abort + cancel, remove the turn's
    # own bubbles (message + pending answer), restore the query. It removes t.userEl/t.pendingEl
    # (per-turn state), NOT shared form flags.
    import re
    stop = re.search(r"const stopTurn = \(\) => \{.*?\n  \};", SRC, re.DOTALL)
    assert stop, "stopTurn not found"
    body = stop.group(0)
    assert "inflight = null" in body, "stop must clear the single source of truth first"
    assert ".controller.abort()" in body and ".reader" in body, "stop must abort + cancel"
    assert "t.userEl.remove()" in body and "t.pendingEl.remove()" in body, "stop undoes both bubbles"
    assert "input.value = t.question" in body, "stop restores the query"
    assert "renderComposer()" in body, "the view is re-derived, not hand-mutated"


def test_stale_turn_cannot_touch_the_view():
    # Each turn captures its own `t`; every async step re-checks `inflight === t` and bails if
    # superseded/stopped — so a stopped turn's late fetch/stream continuation never mutates the
    # UI. This (not a `_stopped` flag) is what keeps the view from drifting.
    assert "inflight !== t" in SRC
    assert "if (inflight === t)" in SRC          # token/step render + finally are gated on it
    # the no-terminal-event error path must sit behind the liveness check
    import re
    guarded = re.search(
        r"await _readStream\(.*?if\s*\(\s*inflight\s*!==\s*t\s*\)\s*return.*?if\s*\(\s*!seenDone\s*\)",
        SRC, re.DOTALL,
    )
    assert guarded, "the inflight!==t guard must precede the no-terminal-event error path"


def test_streaming_autoscroll_is_pinned_not_forced():
    # Bug: _pushToken scrolled to the bottom on EVERY token, yanking the viewport away
    # from a reader scrolling up. Fix: the log tracks a bottom-pin released on scroll-up;
    # token appends only auto-scroll while pinned.
    import re
    # A scroll listener computes the pin from the log's scroll geometry.
    listener = re.search(
        r"addEventListener\(\s*'scroll'.*?scrollHeight.*?scrollTop.*?clientHeight",
        SRC, re.DOTALL,
    )
    assert listener, "log needs a scroll listener that derives the bottom-pin from geometry"
    assert "_pinned" in SRC
    # _pushToken's scrollIntoView must be gated on the pin, not unconditional.
    push = re.search(r"function _pushToken\(.*?\n\}", SRC, re.DOTALL)
    assert push, "could not locate _pushToken"
    body = push.group(0)
    assert "scrollIntoView" in body
    assert "_pinned" in body, "_pushToken must gate its scroll on the bottom-pin"
