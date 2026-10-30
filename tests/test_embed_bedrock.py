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
    loader = importlib.machinery.SourceFileLoader("embed_bedrock", str(ROOT / "bin" / "embed-bedrock"))
    spec = importlib.util.spec_from_loader("embed_bedrock", loader)
    m = importlib.util.module_from_spec(spec); loader.exec_module(m); return m


def _fake_boto3(invoke):
    """A boto3 stand-in whose client.invoke_model delegates to `invoke(modelId, body_dict)`,
    wrapping the returned payload dict in a StreamingBody-like .read()."""
    class _Body:
        def __init__(self, payload): self._b = json.dumps(payload).encode()
        def read(self): return self._b

    class _Client:
        def invoke_model(self, modelId, body):
            return {"body": _Body(invoke(modelId, json.loads(body)))}

    class _Boto3:
        def client(self, service, region_name=None):
            assert service == "bedrock-runtime"
            return _Client()

    return _Boto3()


def _run(shim, monkeypatch, stdin, invoke, dims=1024, extra=None):
    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3(invoke))
    argv = ["embed-bedrock", "--model", "amazon.titan-embed-text-v2:0",
            "--region", "eu-central-1", "--dimensions", str(dims)] + (extra or [])
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return shim.main()


def test_to_body_carries_dimensions_and_normalize():
    shim = _shim()
    body = json.loads(shim.to_body("hola mundo", 512, True))
    assert body == {"inputText": "hola mundo", "dimensions": 512, "normalize": True}


def test_emits_one_line_per_chunk_keyed_by_ref():
    shim = _shim()
    seen = []

    def invoke(model, body):
        seen.append(body["inputText"])
        assert body["dimensions"] == 1024            # the requested width reaches Titan on every call
        return {"embedding": [0.1] * 1024, "inputTextTokenCount": 3}

    import _pytest.monkeypatch as mp
    m = mp.MonkeyPatch()
    stdin = '{"ref":"d1:0","text":"alpha"}\n{"ref":"d1:1","text":"beta"}\n'
    out = io.StringIO()
    m.setattr(sys, "stdout", out)
    rc = _run(shim, m, stdin, invoke)
    m.undo()
    assert rc == 0
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert [l["ref"] for l in lines] == ["d1:0", "d1:1"]           # ref re-attached in order
    assert all(l["dim"] == 1024 and len(l["vector"]) == 1024 for l in lines)
    assert all(l["model"] == "amazon.titan-embed-text-v2:0" for l in lines)  # provenance = the model invoked
    assert seen == ["alpha", "beta"]


def test_empty_input_is_valid_empty_embed(monkeypatch):
    shim = _shim()
    rc = _run(shim, monkeypatch, "\n  \n", lambda m, b: pytest.fail("must not call Bedrock on empty input"))
    assert rc == 0


def test_wrong_width_vector_exits_nonzero(monkeypatch):
    # the passport bakes 1024; a 512-wide vector must stop the build, not be written
    shim = _shim()
    rc = _run(shim, monkeypatch, '{"ref":"d1:0","text":"x"}\n',
              lambda m, b: {"embedding": [0.0] * 512})
    assert rc == 4


def test_malformed_response_exits_nonzero(monkeypatch):
    shim = _shim()
    rc = _run(shim, monkeypatch, '{"ref":"d1:0","text":"x"}\n',
              lambda m, b: {"inputTextTokenCount": 3})       # no "embedding" key
    assert rc == 3


def test_requires_dimensions(monkeypatch):
    """--dimensions is required — no silent default of the baked width (no fallback)."""
    shim = _shim()
    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3(lambda m, b: {"embedding": [0.0] * 1024}))
    monkeypatch.setattr(sys, "argv",
                        ["embed-bedrock", "--model", "m1", "--region", "eu-central-1"])
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"ref":"d1:0","text":"x"}\n'))
    with pytest.raises(SystemExit) as e:
        shim.main()
    assert e.value.code != 0
