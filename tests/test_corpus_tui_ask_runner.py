# tests/test_corpus_tui_ask_runner.py
import json
from pathlib import Path

from shapes.corpus.renderer.tui import ask_runner


def test_build_ask_cmd_omits_where_when_empty():
    cmd = ask_runner.build_ask_cmd("mo", Path("/c"), "answer", "¿q?",
                                   grounding=1.0, mode="hybrid", where="")
    assert "--where" not in cmd
    assert cmd[:5] == ["mo", "corpus", "ask", "/c", "answer"]
    assert "--json" in cmd and "--grounding" in cmd and "--mode" in cmd


def test_build_ask_cmd_includes_where_when_set():
    cmd = ask_runner.build_ask_cmd("mo", Path("/c"), "answer", "¿q?",
                                   grounding=0.5, mode="vector", where="visibility == general")
    assert cmd[cmd.index("--where") + 1] == "visibility == general"


def test_build_save_cmd_definition_only_has_no_stdin_marker():
    cmd, stdin = ask_runner.build_save_cmd(
        "mo", Path("/c"), "esi",
        {"ask": "answer", "question": "¿q?", "grounding": 1.0, "mode": "hybrid", "where": None},
        record=None, definition_only=True)
    assert "--definition-only" in cmd
    assert stdin is None


def test_build_save_cmd_with_record_pipes_json():
    record = {"ask": "answer", "answer": "x", "passages": []}
    cmd, stdin = ask_runner.build_save_cmd(
        "mo", Path("/c"), "esi",
        {"ask": "answer", "question": "¿q?", "grounding": 1.0, "mode": "hybrid", "where": None},
        record=record, definition_only=False)
    assert "--definition-only" not in cmd
    assert json.loads(stdin) == record
