# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import importlib.machinery
import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(binname, modname):
    loader = importlib.machinery.SourceFileLoader(modname, str(ROOT / "bin" / binname))
    spec = importlib.util.spec_from_loader(modname, loader)
    m = importlib.util.module_from_spec(spec); loader.exec_module(m); return m


def _fake_boto3(captured, converse_kind):
    """boto3 stand-in that records the `config` kwarg and returns a minimal happy
    response for whichever call the wrapper makes (converse or converse_stream)."""
    class _Client:
        def converse(self, **k):
            return {"output": {"message": {"content": [{"text": "ok"}]}},
                    "usage": {"inputTokens": 1, "outputTokens": 1},
                    "metrics": {"latencyMs": 1}, "stopReason": "end_turn"}
        def converse_stream(self, **k):
            return {"stream": iter([
                {"contentBlockDelta": {"delta": {"text": "ok"}}},
                {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1}}}])}

    class _Boto3:
        def client(self, service, region_name=None, config=None):
            captured["config"] = config
            return _Client()
    return _Boto3()


def _run(binname, modname, converse_kind, monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3(captured, converse_kind))
    monkeypatch.setattr(sys, "argv", [binname, "--model", "m", "--region",
                                      "eu-central-1", "--max-tokens", "128"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("prompt"))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    m = _load(binname, modname)
    rc = m.main()
    assert rc == 0, f"wrapper exited {rc}"
    return captured["config"]


def test_claude_bedrock_uses_adaptive_retry(monkeypatch):
    cfg = _run("claude-bedrock", "claude_bedrock", "converse", monkeypatch)
    assert cfg.retries == {"max_attempts": 4, "mode": "adaptive"}


def test_claude_bedrock_json_uses_adaptive_retry(monkeypatch):
    cfg = _run("claude-bedrock-json", "claude_bedrock_json", "converse", monkeypatch)
    assert cfg.retries == {"max_attempts": 4, "mode": "adaptive"}


def test_claude_bedrock_stream_uses_adaptive_retry(monkeypatch):
    cfg = _run("claude-bedrock-stream", "claude_bedrock_stream", "converse_stream", monkeypatch)
    assert cfg.retries == {"max_attempts": 4, "mode": "adaptive"}
