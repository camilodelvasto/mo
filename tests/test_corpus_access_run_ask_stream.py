# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import json
from pathlib import Path

import pytest

from shapes.corpus.access import run_ask
from shapes.corpus.access.errors import AskError, CitationError, SynthesisError


def test_synthesize_stream_yields_tokens_and_fills_meta(monkeypatch):
    # Stub the stream binding's subprocess: emit two token lines + a done line.
    ndjson = "\n".join([
        json.dumps({"event": "token", "text": "Hola "}),
        json.dumps({"event": "token", "text": "mundo"}),
        json.dumps({"event": "done", "model": "m",
                    "usage": {"output_tokens": 2}, "cost_usd": 0.02}),
    ]) + "\n"

    class _W:
        def write(self, b): pass
        def close(self): pass
    class _R:
        def read(self): return b""
    class _Proc:
        def __init__(self): self.stdin = _W(); self.stdout = iter(ndjson.splitlines(keepends=True))
        def wait(self): return 0
        stderr = _R()

    monkeypatch.setattr(run_ask.capabilities, "load_table", lambda mr: {
        "api.claude-json": {"stream": ["bin/claude-stream"], "reads": "stdin",
                            "emits": "envelope", "run": ["x"]}})
    monkeypatch.setattr(run_ask.capabilities, "resolve",
                        lambda name, table: table[name])
    monkeypatch.setattr(run_ask.subprocess, "Popen", lambda *a, **k: _Proc())

    ask = {"synthesize": {"uses": "api.claude-json", "prompt": "${question}"}}
    meta = {}
    toks = list(run_ask._synthesize_stream(ask, {}, "q", [], None, 1.0, [], meta))
    assert "".join(toks) == "Hola mundo"
    assert meta["model"] == "m" and meta["cost_usd"] == 0.02


def test_synthesize_stream_missing_stream_binding_raises(monkeypatch):
    monkeypatch.setattr(run_ask.capabilities, "load_table", lambda mr: {
        "api.claude-json": {"run": ["x"], "reads": "stdin", "emits": "envelope"}})
    monkeypatch.setattr(run_ask.capabilities, "resolve", lambda n, t: t[n])
    ask = {"synthesize": {"uses": "api.claude-json", "prompt": "${question}"}}
    with pytest.raises(run_ask.AskError):
        list(run_ask._synthesize_stream(ask, {}, "q", [], None, 1.0, [], {}))


# --- helpers for run_ask_stream integration tests ---

_ASK = {
    "id": "converse",
    "retrieve": {"mode": "hybrid", "k": 8, "status": "Retrieving…"},
    "decompose": {"uses": "api.claude-json", "prompt": "${question}",
                  "status": "Thinking…"},
    "synthesize": {"uses": "api.claude-json", "prompt": "${question}", "titled": True},
}

_ASK_NOCITE = {
    "id": "converse",
    "retrieve": {"mode": "hybrid", "k": 8, "status": "Retrieving…"},
    "synthesize": {"uses": "api.claude-json", "prompt": "${question}"},
}

_ASK_CITE = {
    "id": "converse",
    "retrieve": {"mode": "hybrid", "k": 8},
    "synthesize": {"uses": "api.claude-json", "prompt": "${question}"},
    "check": "citations",
}

_PASSAGE = {"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "x", "name": "doc-a.md"}


def _stub_pipeline(monkeypatch, ask, passages=None, history=None):
    """Stub all pipeline internals except _synthesize_stream so integration tests
    control exactly what the stream generator does. Returns the stubbed ask dict."""
    if passages is None:
        passages = [_PASSAGE]

    monkeypatch.setattr(run_ask.reconcile, "reconcile", lambda *a: None)
    # the binding table: the ask's synthesize capability declares reads: stdin (a prompt)
    monkeypatch.setattr(run_ask.capabilities, "load_table", lambda mr: {"capabilities": {
        ask["synthesize"]["uses"]: {"stream": ["x"], "reads": "stdin", "emits": "envelope"}}})
    monkeypatch.setattr(run_ask.askfile, "load_asks", lambda corpus: {"asks": [ask]})
    monkeypatch.setattr(run_ask.askfile, "resolve_ask", lambda asks, ask_id: ask)
    monkeypatch.setattr(run_ask, "_load_flow", lambda corpus: {})
    monkeypatch.setattr(run_ask.index, "open_index", lambda corpus: _FakeConn())
    monkeypatch.setattr(run_ask, "_projections", lambda conn: {})
    monkeypatch.setattr(run_ask.flt, "doc_ids_for", lambda where, flow, proj: None)
    monkeypatch.setattr(run_ask.retrieve, "retrieve_many",
                        lambda conn, mode, k, scope, queries, embed: list(passages))
    monkeypatch.setattr(run_ask, "_attach_names", lambda p, proj: None)
    # _plan_queries is called when ask has a decompose key — stub it too
    monkeypatch.setattr(run_ask, "_plan_queries",
                        lambda ask, q, hist, mr: [q])
    # title is best-effort and runs in a thread; stub it out
    monkeypatch.setattr(run_ask, "_title", lambda ask, q, mr: "Fake title")
    return ask


class _FakeConn:
    def close(self): pass


# --- _stream_error_kind unit tests ---

def test_stream_error_kind_citation_error():
    assert run_ask._stream_error_kind(CitationError("bad")) == "citation_check"


def test_stream_error_kind_synthesis_error():
    assert run_ask._stream_error_kind(SynthesisError("fail")) == "synthesis_failed"


def test_stream_error_kind_plain_ask_error():
    assert run_ask._stream_error_kind(AskError("no ask")) == "unknown_ask"


# --- error→event mapping: the contract chat.js renders off ---

def test_run_ask_stream_synthesis_failure_yields_error_no_done(monkeypatch):
    """SynthesisError in _synthesize_stream must surface as error event with
    kind=synthesis_failed. No done event must follow it."""
    _stub_pipeline(monkeypatch, _ASK_NOCITE)

    def _boom(*a, **k):
        raise SynthesisError("subprocess died")
        yield  # make it a generator

    monkeypatch.setattr(run_ask, "_synthesize_stream", _boom)

    events = list(run_ask.run_ask_stream(
        Path("/fake/corpus"), Path("/fake/machine"), "converse", "¿q?"))

    kinds = [e["event"] for e in events]
    assert "done" not in kinds
    last = events[-1]
    assert last["event"] == "error"
    assert last["kind"] == "synthesis_failed"


def test_run_ask_stream_citation_check_failure_yields_error_no_done(monkeypatch):
    """CitationError from _check_citations must surface as error event with
    kind=citation_check. No done event must follow it."""
    _stub_pipeline(monkeypatch, _ASK_CITE, passages=[_PASSAGE])

    def _two_tokens(*a, **k):
        yield "some text [ffffffffffff:bad] fabricated"

    monkeypatch.setattr(run_ask, "_synthesize_stream", _two_tokens)
    monkeypatch.setattr(run_ask, "_check_citations",
                        lambda answer, passages: (_ for _ in ()).throw(
                            CitationError("fabricated citation")))

    events = list(run_ask.run_ask_stream(
        Path("/fake/corpus"), Path("/fake/machine"), "converse", "¿q?"))

    kinds = [e["event"] for e in events]
    assert "done" not in kinds
    last = events[-1]
    assert last["event"] == "error"
    assert last["kind"] == "citation_check"


# --- happy-path event ordering ---

def test_run_ask_stream_happy_path_event_order(monkeypatch):
    """With decompose+retrieve status declared, sources: true, and two tokens
    yielded, the event sequence must be: step(decompose) → step(retrieve) →
    token → token → sources → done. title is absent because history is non-empty."""
    ask = {
        "id": "converse",
        "retrieve": {"mode": "hybrid", "k": 8, "status": "Retrieving…"},
        "decompose": {"uses": "api.claude-json", "prompt": "${question}",
                      "status": "Thinking…"},
        "synthesize": {"uses": "api.claude-json", "prompt": "${question}",
                       "titled": True},
        "sources": True,
    }
    _stub_pipeline(monkeypatch, ask)

    def _two_tokens(*a, **k):
        yield "Hola "
        yield "mundo"

    monkeypatch.setattr(run_ask, "_synthesize_stream", _two_tokens)

    history = [{"role": "user", "content": "hola"}]
    events = list(run_ask.run_ask_stream(
        Path("/fake/corpus"), Path("/fake/machine"), "converse", "¿q?",
        history=history))

    kinds = [e["event"] for e in events]
    # title must be absent (history is non-empty → want_title=False)
    assert "title" not in kinds
    # ordering contract
    assert kinds.index("step") < kinds.index("token")
    # two step events (decompose then retrieve)
    assert kinds.count("step") == 2
    # two token events
    assert kinds.count("token") == 2
    token_indices = [i for i, k in enumerate(kinds) if k == "token"]
    sources_idx = kinds.index("sources")
    done_idx = kinds.index("done")
    assert max(token_indices) < sources_idx < done_idx
    # token text
    assert events[token_indices[0]]["text"] == "Hola "
    assert events[token_indices[1]]["text"] == "mundo"


def _stream_kinds(monkeypatch, ask):
    _stub_pipeline(monkeypatch, ask)

    def _two_tokens(*a, **k):
        yield "Hola "
        yield "mundo"

    monkeypatch.setattr(run_ask, "_synthesize_stream", _two_tokens)
    events = list(run_ask.run_ask_stream(
        Path("/fake/corpus"), Path("/fake/machine"), "converse", "¿q?",
        history=[{"role": "user", "content": "hola"}]))
    return [e["event"] for e in events]


def test_run_ask_stream_sources_false_streams_none(monkeypatch):
    """sources: false — the answer uses the corpus without ever exposing it."""
    kinds = _stream_kinds(monkeypatch, {
        "id": "converse",
        "retrieve": {"mode": "hybrid", "k": 8},
        "synthesize": {"uses": "api.claude-json", "prompt": "${question}"},
        "sources": False,
    })
    assert "sources" not in kinds
    assert kinds.count("token") == 2 and kinds[-1] == "done"


def test_run_ask_stream_sources_absent_streams_none(monkeypatch):
    """Showing sources is an explicit declaration: an ask without the key
    streams none — absence is off, never a hidden default."""
    kinds = _stream_kinds(monkeypatch, {
        "id": "converse",
        "retrieve": {"mode": "hybrid", "k": 8},
        "synthesize": {"uses": "api.claude-json", "prompt": "${question}"},
    })
    assert "sources" not in kinds
    assert kinds.count("token") == 2 and kinds[-1] == "done"
