import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from shapes.corpus.service import app as appmod
from shapes.corpus.service.app import create_app
from shapes.corpus.commands._access_cli import error_kind
from shapes.corpus.access.errors import AskError, CitationError, SynthesisError, TitleError
from tests.test_corpus_service_reads import _corpus


def _fake_proc(stdout="", stderr="", code=0):
    return SimpleNamespace(stdout=stdout.encode(), stderr=stderr.encode(), returncode=code)


def _stub_mo(monkeypatch, proc):
    """Pretend `mo` is on PATH and returns `proc` — so route tests never shell the
    real CLI and never depend on the test environment's PATH."""
    monkeypatch.setattr(appmod.shutil, "which", lambda _name: "/usr/bin/mo")
    monkeypatch.setattr(appmod.subprocess, "run", lambda *a, **k: proc)


def test_ask_route_returns_record(tmp_path, monkeypatch):
    corpus = _corpus(tmp_path)
    record = {"ask": "converse", "answer": "hi [aaaaaaaaaaaa:r1]", "passages": [],
              "queries": ["standalone query"]}
    _stub_mo(monkeypatch, _fake_proc(json.dumps(record)))
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q", "history": []})
    assert r.status_code == 200
    assert r.json()["answer"].startswith("hi")
    assert r.json()["queries"] == ["standalone query"]   # the record relays verbatim


def test_ask_route_rejects_malformed_history_turn(tmp_path):
    # a turn missing `content` is rejected at the boundary (422) before the CLI runs,
    # so the "--json always emits a typed envelope" invariant is never reached crashing.
    corpus = _corpus(tmp_path)
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q", "history": [{"role": "user"}]})
    assert r.status_code == 422


def test_kind_contract_cli_and_serve_agree():
    # the kinds the CLI emits for specific errors must be exactly what the serve maps;
    # one source (_ASK_STATUS) tested against the other (error_kind) so they can't drift.
    assert appmod._ASK_STATUS[error_kind(CitationError("x"))] == 422
    assert appmod._ASK_STATUS[error_kind(SynthesisError("x"))] == 502
    assert appmod._ASK_STATUS[error_kind(AskError("x"))] == 404
    # a bad/empty title is a synthesis failure (502), never an unknown ask (404)
    assert appmod._ASK_STATUS[error_kind(TitleError("x"))] == 502
    assert "engine_error" not in appmod._ASK_STATUS          # intentionally the 500 default


def test_ask_route_maps_citation_check_to_422(tmp_path, monkeypatch):
    corpus = _corpus(tmp_path)
    env = {"error": {"kind": "citation_check", "detail": "fabricated [x:y]"}}
    _stub_mo(monkeypatch, _fake_proc(json.dumps(env), code=1))
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q"})
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "citation_check"


def test_ask_route_unknown_ask_404(tmp_path, monkeypatch):
    corpus = _corpus(tmp_path)
    env = {"error": {"kind": "unknown_ask", "detail": "no ask named 'nope'"}}
    _stub_mo(monkeypatch, _fake_proc(json.dumps(env), code=1))
    client = TestClient(create_app(corpus))
    r = client.post("/ask/nope", json={"question": "q"})
    assert r.status_code == 404


def test_ask_route_engine_error_defaults_500(tmp_path, monkeypatch):
    corpus = _corpus(tmp_path)
    env = {"error": {"kind": "engine_error", "detail": "bad where"}}
    _stub_mo(monkeypatch, _fake_proc(json.dumps(env), code=1))
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q"})
    assert r.status_code == 500


def test_ask_route_missing_mo_is_502(tmp_path, monkeypatch):
    corpus = _corpus(tmp_path)
    monkeypatch.setattr(appmod.shutil, "which", lambda _name: None)
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q"})
    assert r.status_code == 502
    assert "PATH" in r.json()["detail"]


def test_ask_route_timeout_is_504(tmp_path, monkeypatch):
    import subprocess
    corpus = _corpus(tmp_path)
    monkeypatch.setattr(appmod.shutil, "which", lambda _name: "/usr/bin/mo")

    def _hang(*a, **k):
        raise subprocess.TimeoutExpired(cmd="mo", timeout=600)
    monkeypatch.setattr(appmod.subprocess, "run", _hang)
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q"})
    assert r.status_code == 504


def test_cors_header_present_for_allowed_origin(tmp_path):
    corpus = _corpus(tmp_path)
    client = TestClient(create_app(corpus, allow_origins=["http://grove.test"]))
    r = client.get("/status", headers={"origin": "http://grove.test"})
    assert r.headers.get("access-control-allow-origin") == "http://grove.test"
