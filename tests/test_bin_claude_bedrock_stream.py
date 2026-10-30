# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import importlib.machinery
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _shim():
    loader = importlib.machinery.SourceFileLoader(
        "claude_bedrock_stream", str(ROOT / "bin" / "claude-bedrock-stream"))
    spec = importlib.util.spec_from_loader("claude_bedrock_stream", loader)
    m = importlib.util.module_from_spec(spec); loader.exec_module(m); return m


def _fake_boto3(events, raise_exc=None):
    """boto3 stand-in whose client.converse_stream returns {"stream": iter(events)}
    (or raises raise_exc). `events` is a list of ConverseStream event dicts."""
    class _Client:
        def converse_stream(self, modelId, messages, inferenceConfig):
            if raise_exc is not None:
                raise raise_exc
            return {"stream": iter(events)}

    class _Boto3:
        def client(self, service, region_name=None, config=None):
            assert service == "bedrock-runtime"
            return _Client()
    return _Boto3()


def _run(monkeypatch, stdin, events, raise_exc=None, max_tokens="8192"):
    shim = _shim()
    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3(events, raise_exc))
    monkeypatch.setattr(sys, "argv", ["claude-bedrock-stream", "--model", "m1",
                                      "--region", "eu-central-1", "--max-tokens", max_tokens])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    out = io.StringIO(); monkeypatch.setattr(sys, "stdout", out)
    rc = shim.main()
    return rc, [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]


def _delta(text):
    return {"contentBlockDelta": {"delta": {"text": text}, "contentBlockIndex": 0}}


def _meta():
    return {"metadata": {"usage": {"inputTokens": 5, "outputTokens": 2,
                                   "cacheReadInputTokens": 0}}}


def test_streams_tokens_then_done(monkeypatch):
    rc, lines = _run(monkeypatch, "hola", [_delta("Ho"), _delta("la"), _meta()])
    assert rc == 0
    tokens = [l["text"] for l in lines if l["event"] == "token"]
    done = [l for l in lines if l["event"] == "done"]
    assert "".join(tokens) == "Hola"
    assert done and done[0]["model"] == "m1"
    assert done[0]["cost_usd"] is None
    assert done[0]["usage"] == {"input_tokens": 5, "output_tokens": 2,
                                "cache_read_input_tokens": 0}


def test_converse_stream_error_is_error_event(monkeypatch):
    rc, lines = _run(monkeypatch, "hola", [], raise_exc=RuntimeError("throttled"))
    assert rc == 2
    assert lines[-1]["event"] == "error" and lines[-1]["kind"] == "synthesis_failed"
    assert not any(l["event"] == "done" for l in lines)


def test_empty_generation_is_error(monkeypatch):
    rc, lines = _run(monkeypatch, "hola", [_meta()])   # metadata only, no deltas
    assert rc == 3
    assert lines[-1]["event"] == "error" and lines[-1]["kind"] == "synthesis_failed"


def test_empty_prompt_exits_before_calling_bedrock(monkeypatch):
    rc, lines = _run(monkeypatch, "   \n",
                     [_delta("should not be reached")])
    assert rc == 1
    assert not any(l["event"] == "token" for l in lines)
