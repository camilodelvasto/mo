# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
from types import SimpleNamespace

from shapes.corpus.engine.runner import _spawn_failure_reason


def _proc(returncode, stdout=b"", stderr=b""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_failure_reason_captures_stdout_when_stderr_empty():
    # claude -p case: error on stdout, stderr empty
    proc = _proc(1, stdout=b"Prompt is too long ... (limit 1,000,000)", stderr=b"")
    reason = _spawn_failure_reason(proc)
    assert "Prompt is too long" in reason
    assert reason != "exit 1"


def test_failure_reason_captures_stderr():
    proc = _proc(2, stdout=b"", stderr=b"boom on stderr")
    assert "boom on stderr" in _spawn_failure_reason(proc)


def test_failure_reason_includes_both_streams():
    proc = _proc(1, stdout=b"out-detail", stderr=b"err-detail")
    reason = _spawn_failure_reason(proc)
    assert "out-detail" in reason and "err-detail" in reason


def test_failure_reason_falls_back_to_exit_code_when_silent():
    assert _spawn_failure_reason(_proc(3)) == "exit 3"


def test_failure_reason_is_bounded():
    proc = _proc(1, stdout=b"x" * 5000)
    assert len(_spawn_failure_reason(proc)) <= 2000
