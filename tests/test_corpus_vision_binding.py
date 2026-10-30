# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The wire shape is DECLARED on the binding, not assumed by convention. A synthesize
binding `reads: stdin` takes a prompt; `reads: envelope` takes the multimodal
envelope. An ask that declares attachments: must bind to an envelope reader — the
engine refuses the mismatch before it spends a retrieval, and never feeds JSON to a
prompt reader (which would answer about JSON, silently)."""
import base64, hashlib, json
import pytest
from shapes.corpus.access import run_ask, attest
from shapes.corpus.access.errors import AskError
from shapes.corpus.engine.errors import CapabilityError

SECRET = b"secret-xyz"
ATT_ASK = {"id": "read", "attachments": {"accept": ["image"]},
           "synthesize": {"uses": "api.claude-vision", "prompt": "${question}"},
           "retrieve": {"mode": "none"}}


def _table(reads):
    return {"capabilities": {"api.claude-vision": {"reads": reads, "emits": "envelope",
                                                    "stream": ["vision-bin"]}}}


def _wire(monkeypatch, table):
    monkeypatch.setattr(run_ask.capabilities, "load_table", lambda mr: table)
    monkeypatch.setattr(run_ask.attest, "load_secret", lambda mr: SECRET)
    monkeypatch.setattr(run_ask.reconcile, "reconcile", lambda *a, **k: None)
    monkeypatch.setattr(run_ask.askfile, "load_asks", lambda c: {"asks": []})
    monkeypatch.setattr(run_ask.askfile, "resolve_ask", lambda asks, i: ATT_ASK)
    monkeypatch.setattr(run_ask, "_load_flow", lambda c: {})
    touched = {}
    monkeypatch.setattr(run_ask.retrieve, "retrieve_many",
                        lambda *a, **k: touched.setdefault("retrieved", True) and [])
    return touched


def test_attachments_ask_on_a_prompt_binding_is_refused_before_retrieval(monkeypatch):
    touched = _wire(monkeypatch, _table("stdin"))
    events = list(run_ask.run_ask_stream(None, None, "read", "hello"))
    assert events[-1]["event"] == "error" and events[-1]["kind"] == "capability_binding"
    assert "api.claude-vision" in events[-1]["detail"] and "reads: envelope" in events[-1]["detail"]
    assert "retrieved" not in touched, "refused before spending a retrieval"


def test_vision_stream_requires_an_envelope_reader(monkeypatch):
    monkeypatch.setattr(run_ask.capabilities, "load_table", lambda mr: _table("stdin"))
    with pytest.raises(CapabilityError, match="reads: envelope"):
        list(run_ask._synthesize_stream_vision(ATT_ASK, {}, "q", [], None, 0.5, [], [], {}))


def test_text_stream_requires_a_prompt_reader(monkeypatch):
    plain = {"id": "plain", "synthesize": {"uses": "api.claude-vision", "prompt": "${question}"}}
    monkeypatch.setattr(run_ask.capabilities, "load_table", lambda mr: _table("envelope"))
    with pytest.raises(CapabilityError, match="reads: stdin"):
        list(run_ask._synthesize_stream(plain, {}, "q", [], None, 0.5, [], {}))


def test_title_on_an_envelope_reader_streams_a_title_envelope(monkeypatch):
    """The title step uses the ask's OWN capability. On an envelope reader it sends a
    title envelope down the stream binding and joins the tokens — one capability, one
    wire shape, no second run: binding."""
    monkeypatch.setattr(run_ask.capabilities, "load_table", lambda mr: _table("envelope"))
    seen = {}
    def fake_stream(binding, payload, meta_out, name):
        seen["payload"] = json.loads(payload); seen["binding"] = binding
        yield "Color "; yield "de la imagen"
    monkeypatch.setattr(run_ask, "_stream_capability", fake_stream)
    title = run_ask._title(ATT_ASK, "¿de qué color es?", None)
    assert title == "Color de la imagen"
    env = seen["payload"]
    assert set(env) == {"system", "messages"} and env["messages"][-1]["role"] == "user"
    assert "¿de qué color es?" in env["messages"][-1]["content"][0]["text"]
    assert all(b["type"] == "text" for b in env["messages"][-1]["content"]), "title is a text step"


def test_title_on_an_envelope_reader_degrades_to_the_trimmed_question(monkeypatch):
    monkeypatch.setattr(run_ask.capabilities, "load_table", lambda mr: _table("envelope"))
    def failing(binding, payload, meta_out, name):
        raise run_ask.SynthesisError("boom"); yield
    monkeypatch.setattr(run_ask, "_stream_capability", failing)
    assert run_ask._title(ATT_ASK, "hola mundo", None) == run_ask._trim_question("hola mundo")
