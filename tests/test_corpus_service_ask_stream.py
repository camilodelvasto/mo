# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import io
import json
import os
from fastapi.testclient import TestClient
from shapes.corpus.service import app as appmod
from shapes.corpus.service.app import create_app
from tests.test_corpus_service_reads import _corpus


class _FakePopen:
    """A real OS pipe pre-loaded with the NDJSON lines, so the relay's fileno()/os.read/
    select path runs against an actual fd (not an iterator). The write end is closed so
    the read side sees EOF once the data drains."""
    def __init__(self, lines):
        r, w = os.pipe()
        os.write(w, b"".join(l.encode() for l in lines))
        os.close(w)
        self.stdout = os.fdopen(r, "rb", buffering=0)
        self.stderr = io.BytesIO(b"")
        self.returncode = 0
    def wait(self, timeout=None): return 0
    def poll(self): return 0
    def kill(self): pass


def test_stream_accept_header_relays_ndjson(tmp_path, monkeypatch):
    corpus = _corpus(tmp_path)
    lines = [json.dumps({"event": "token", "text": "hi"}) + "\n",
             json.dumps({"event": "done", "model": "m"}) + "\n"]
    monkeypatch.setattr(appmod.shutil, "which", lambda _n: "/usr/bin/mo")
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda *a, **k: _FakePopen(lines))
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q", "history": []},
                    headers={"Accept": "application/x-ndjson"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    got = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert [e["event"] for e in got] == ["token", "done"]


def test_blocking_path_unchanged_without_accept(tmp_path, monkeypatch):
    corpus = _corpus(tmp_path)
    from types import SimpleNamespace
    record = {"ask": "converse", "answer": "hi", "passages": []}
    monkeypatch.setattr(appmod.shutil, "which", lambda _n: "/usr/bin/mo")
    monkeypatch.setattr(appmod.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stdout=json.dumps(record).encode(),
                                                        stderr=b"", returncode=0))
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q", "history": []})
    assert r.status_code == 200 and r.json()["answer"] == "hi"


def test_dead_subprocess_emits_error_event(tmp_path, monkeypatch):
    """A crashed ask must not close the stream silently — the 200 is already on
    the wire, so the error event IS the error channel (the saturado-502 lesson)."""
    corpus = _corpus(tmp_path)
    lines = [json.dumps({"event": "step", "text": "Entendiendo…"}) + "\n"]
    fake = _FakePopen(lines)
    fake.returncode = 1
    fake.wait = lambda timeout=None: 1
    fake.stderr = io.BytesIO(
        b"Traceback (most recent call last):\n  ...\n"
        b"sqlite3.OperationalError: unable to open database file\n")
    monkeypatch.setattr(appmod.shutil, "which", lambda _n: "/usr/bin/mo")
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda *a, **k: fake)
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q", "history": []},
                    headers={"Accept": "application/x-ndjson"})
    got = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert got[-1]["event"] == "error"
    assert got[-1]["kind"] == "ask_failed"
    assert "unable to open database file" in got[-1]["detail"]


def test_error_event_detail_reaches_the_box_log(tmp_path, monkeypatch, capsys):
    """Errors ride stdout as events — to the client, which flattens them into a
    generic string. The box log read only stderr, so a wrapper that reported its
    failure properly (error event, exit 1, silent stderr) left `ask stream exited
    1:` with nothing after the colon. The relay must remember the last error event
    and log its detail — a failed ask names its reason on the box, always."""
    corpus = _corpus(tmp_path)
    lines = [json.dumps({"event": "step", "text": "Buscando…"}) + "\n",
             json.dumps({"event": "error", "kind": "synthesis_failed",
                         "detail": "ThrottlingException: rate exceeded"}) + "\n"]
    fake = _FakePopen(lines)
    fake.returncode = 1
    fake.wait = lambda timeout=None: 1          # stderr stays empty: events ARE the channel
    monkeypatch.setattr(appmod.shutil, "which", lambda _n: "/usr/bin/mo")
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda *a, **k: fake)
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q", "history": []},
                    headers={"Accept": "application/x-ndjson"})
    assert "ThrottlingException" in capsys.readouterr().err   # the box log names the reason
    got = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    # the trailing ask_failed event carries the reason too, not a bare "ask exited 1"
    assert got[-1]["kind"] == "ask_failed"
    assert "ThrottlingException" in got[-1]["detail"]


def test_garbage_error_lookalike_line_still_ends_with_ask_failed(tmp_path, monkeypatch):
    """The sieve matches any line carrying '"error"'; the exit-time parse must
    survive one that is valid JSON but not an event object. A crashing wrapper is
    exactly when stdout goes off-protocol — the terminal ask_failed event must
    still close the stream."""
    corpus = _corpus(tmp_path)
    lines = ['["error"]' + "\n"]                # valid JSON, not an object
    fake = _FakePopen(lines)
    fake.returncode = 1
    fake.wait = lambda timeout=None: 1
    monkeypatch.setattr(appmod.shutil, "which", lambda _n: "/usr/bin/mo")
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda *a, **k: fake)
    client = TestClient(create_app(corpus))
    r = client.post("/ask/converse", json={"question": "q", "history": []},
                    headers={"Accept": "application/x-ndjson"})
    got = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert got[-1] == {"event": "error", "kind": "ask_failed", "detail": "ask exited 1"}
