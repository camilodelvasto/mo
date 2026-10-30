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
    loader = importlib.machinery.SourceFileLoader("claude_bedrock", str(ROOT / "bin" / "claude-bedrock"))
    spec = importlib.util.spec_from_loader("claude_bedrock", loader)
    m = importlib.util.module_from_spec(spec); loader.exec_module(m); return m


def test_to_text_joins_content_blocks():
    shim = _shim()
    resp = {"output": {"message": {"content": [{"text": "Photosynthesis converts sunlight "},
                                               {"text": "into glucose [aaaaaaaaaaaa:r1]."}]}},
            "usage": {"inputTokens": 50, "outputTokens": 12}, "stopReason": "end_turn"}
    assert shim.to_text(resp) == "Photosynthesis converts sunlight into glucose [aaaaaaaaaaaa:r1]."


def test_to_text_empty_raises_or_returns_empty_consistently():
    shim = _shim()
    # a response with no text blocks must NOT silently yield a fake answer — to_text returns ""
    resp = {"output": {"message": {"content": []}}, "usage": {}, "stopReason": "end_turn"}
    assert shim.to_text(resp) == ""   # main() turns an empty answer into a non-zero exit (no fallback)


def test_main_passes_max_tokens_cap_to_converse(monkeypatch, capsys):
    """The per-call output cap reaches Bedrock: converse is called with
    inferenceConfig.maxTokens = the --max-tokens value."""
    shim = _shim()
    captured = {}

    class _FakeClient:
        def converse(self, **kwargs):
            captured.update(kwargs)
            return {"output": {"message": {"content": [{"text": "ok [aaaaaaaaaaaa:r1]"}]}},
                    "stopReason": "end_turn"}

    class _FakeBoto3:
        def client(self, service, region_name=None, config=None):
            captured["service"], captured["region_name"] = service, region_name
            return _FakeClient()

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3())
    monkeypatch.setattr(sys, "argv",
                        ["claude-bedrock", "--model", "m1", "--region", "eu-central-1", "--max-tokens", "256"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("a prompt"))

    assert shim.main() == 0
    assert captured["inferenceConfig"] == {"maxTokens": 256}
    assert captured["modelId"] == "m1" and captured["region_name"] == "eu-central-1"
    assert capsys.readouterr().out == "ok [aaaaaaaaaaaa:r1]"


def test_main_requires_max_tokens(monkeypatch):
    """--max-tokens is required — no silent uncapped run (no fallback)."""
    shim = _shim()
    monkeypatch.setattr(sys, "argv", ["claude-bedrock", "--model", "m1", "--region", "eu-central-1"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("a prompt"))
    with pytest.raises(SystemExit) as e:        # argparse exits non-zero on a missing required arg
        shim.main()
    assert e.value.code != 0


def _shim_json():
    loader = importlib.machinery.SourceFileLoader("claude_bedrock_json", str(ROOT / "bin" / "claude-bedrock-json"))
    spec = importlib.util.spec_from_loader("claude_bedrock_json", loader)
    m = importlib.util.module_from_spec(spec); loader.exec_module(m); return m


def test_to_envelope_maps_converse_to_moui_envelope():
    shim = _shim_json()
    resp = {"output": {"message": {"content": [{"text": "Respuesta "}, {"text": "[aaaaaaaaaaaa:r1]."}]}},
            "usage": {"inputTokens": 1200, "outputTokens": 240, "cacheReadInputTokens": 0},
            "metrics": {"latencyMs": 5300}, "stopReason": "end_turn"}
    env = shim.to_envelope(resp, "eu.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert env["answer"] == "Respuesta [aaaaaaaaaaaa:r1]."
    assert env["model"] == "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert env["usage"] == {"input_tokens": 1200, "output_tokens": 240, "cache_read_input_tokens": 0}
    assert env["cost_usd"] is None
    assert env["duration_ms"] == 5300


def test_json_shim_emits_envelope_with_cap(monkeypatch, capsys):
    """The -json shim writes the envelope JSON and passes --max-tokens to converse."""
    shim = _shim_json()
    captured = {}

    class _FakeClient:
        def converse(self, **kwargs):
            captured.update(kwargs)
            return {"output": {"message": {"content": [{"text": "ok [aaaaaaaaaaaa:r1]"}]}},
                    "usage": {"inputTokens": 10, "outputTokens": 5}, "metrics": {"latencyMs": 99},
                    "stopReason": "end_turn"}

    class _FakeBoto3:
        def client(self, service, region_name=None, config=None):
            return _FakeClient()

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3())
    monkeypatch.setattr(sys, "argv",
                        ["claude-bedrock-json", "--model", "m1", "--region", "eu-central-1", "--max-tokens", "512"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("una pregunta"))
    assert shim.main() == 0
    assert captured["inferenceConfig"] == {"maxTokens": 512}
    out = json.loads(capsys.readouterr().out)
    assert out["answer"] == "ok [aaaaaaaaaaaa:r1]" and out["model"] == "m1"
    assert out["usage"]["input_tokens"] == 10 and out["duration_ms"] == 99
