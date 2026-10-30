# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import io
import json
import os
from pathlib import Path
import yaml
from fastapi.testclient import TestClient
from shapes.corpus.service import app as service_app


def _corpus(tmp_path):
    (tmp_path / "corpus.yaml").write_text("flow: ./flow.yaml\n")
    (tmp_path / "flow.yaml").write_text("pipeline: []\n")
    (tmp_path / "ask.yaml").write_text(yaml.safe_dump({"id": "c", "version": 1, "asks": [
        {"id": "read", "attachments": {"accept": ["image"], "max_count": 2, "max_bytes": 999999},
         "synthesize": {"uses": "api.claude-vision", "prompt": "${question}"}}]}))
    return tmp_path


class _FakePopen:
    """A real OS pipe pre-loaded with the NDJSON lines, so the relay's fileno()/os.read/
    select path runs against an actual fd (not an iterator). The write end is closed so
    the read side sees EOF once the data drains."""
    def __init__(self, lines):
        r, w = os.pipe()
        os.write(w, b"".join(l if isinstance(l, bytes) else l.encode() for l in lines))
        os.close(w)
        self.stdout = os.fdopen(r, "rb", buffering=0)
        self.stderr = io.BytesIO(b"")
        self.returncode = 0

    def wait(self, timeout=None): return 0
    def poll(self): return 0
    def kill(self): pass


def test_ask_passes_attachments_to_cli(tmp_path, monkeypatch):
    captured = {}
    lines = [b'{"event":"token","text":"hi"}\n', b'{"event":"done"}\n']

    def _popen(cmd, **k):
        captured["cmd"] = list(cmd)
        # Read the attachments temp file content NOW — before the relay's finally deletes it.
        # The file is still open when _popen is called; the relay only cleans up on exit.
        if "--attachments" in cmd:
            val = cmd[cmd.index("--attachments") + 1]
            payload = Path(val[1:]).read_text() if val.startswith("@") else val
            captured["att_payload"] = payload
        return _FakePopen(lines)

    monkeypatch.setattr(service_app.subprocess, "Popen", _popen)
    monkeypatch.setattr(service_app.shutil, "which", lambda x: "/usr/bin/mo")
    app = service_app.create_app(_corpus(tmp_path), machine_root=tmp_path)
    c = TestClient(app)
    att = {"data": "AA==", "signature": "s", "media_type": "image/webp"}
    r = c.post("/ask/read", headers={"accept": "application/x-ndjson"},
               json={"question": "what is this?", "history": [], "attachments": [att]})
    assert r.status_code == 200
    # the --attachments flag reached the CLI, pointing at a temp file (@) or inline JSON
    cmd = captured["cmd"]
    assert "--attachments" in cmd
    assert json.loads(captured["att_payload"])[0]["signature"] == "s"


# --- the blocking path states its limit ------------------------------------------
# `mo corpus ask` streams attachments; the blocking (JSON) path does not. It used to
# ignore body.attachments entirely — a silent drop — and put history on argv, which a
# single image-carrying turn overflows (Argument list too long).

def _blocking_client(tmp_path):
    return TestClient(service_app.create_app(_corpus(tmp_path), machine_root=tmp_path))


def test_blocking_ask_refuses_attachments_instead_of_dropping_them(tmp_path):
    c = _blocking_client(tmp_path)
    r = c.post("/ask/read", json={"question": "q", "history": [],
                                  "attachments": [{"data": "aW1n", "signature": "s",
                                                   "media_type": "image/webp"}]})
    assert r.status_code == 406
    assert "x-ndjson" in r.json()["detail"]


def test_blocking_ask_refuses_a_history_turn_that_carries_images(tmp_path):
    c = _blocking_client(tmp_path)
    hist = [{"role": "user", "content": "earlier",
             "attachments": [{"data": "aW1n", "signature": "s", "media_type": "image/webp"}]},
            {"role": "assistant", "content": "ok"}]
    r = c.post("/ask/read", json={"question": "q", "history": hist})
    assert r.status_code == 406


# --- the stream acquires nothing until it is read -----------------------------------
# The temp files (base64 images) and the `mo corpus ask` process used to be acquired
# before StreamingResponse was returned. A client that went away before the first
# advance left the files in the temp dir and the process orphaned: the generator's
# finally never ran because the generator never started.

import asyncio
import tempfile
from starlette.requests import Request


def _ask_endpoint(app):
    return next(r.endpoint for r in app.routes
                if getattr(r, "path", None) == "/ask/{name}" and "POST" in r.methods)


def _stream_request():
    return Request({"type": "http", "method": "POST", "path": "/ask/read",
                    "headers": [(b"accept", b"application/x-ndjson")]})


def _att_body():
    return service_app.AskBody(question="q", history=[],
        attachments=[{"data": "aW1n", "signature": "s" * 64, "media_type": "image/webp"}])


def _spilled(spill):
    # only the ask's own temp files: the app keeps other state (a locks dir) in tempdir
    return sorted(spill.glob("ask-*"))


def _drain(resp):
    async def drain():
        return [c async for c in resp.body_iterator]
    return asyncio.run(drain())


def test_nothing_is_acquired_until_the_stream_is_read(tmp_path, monkeypatch):
    spill = tmp_path / "tmp"; spill.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(spill))
    monkeypatch.setattr(service_app.shutil, "which", lambda _: "/usr/bin/mo")
    started = []
    def _popen(cmd, **kw):
        started.append(cmd)
        return _FakePopen([b'{"event":"done"}\n'])
    monkeypatch.setattr(service_app.subprocess, "Popen", _popen)
    app = service_app.create_app(_corpus(tmp_path))

    resp = _ask_endpoint(app)(name="read", body=_att_body(), request=_stream_request())
    assert started == [] and _spilled(spill) == [], "a response never read acquires nothing"

    _drain(resp)
    assert len(started) == 1 and _spilled(spill) == [], "read to the end: ran, then cleaned"


def test_a_stream_that_cannot_start_its_process_says_so_and_cleans(tmp_path, monkeypatch):
    # The 200 is on the wire before Popen runs; its failure is the stream's error event.
    spill = tmp_path / "tmp"; spill.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(spill))
    monkeypatch.setattr(service_app.shutil, "which", lambda _: "/usr/bin/mo")
    def _popen(cmd, **kw):
        raise FileNotFoundError(2, "No such file or directory", cmd[0])
    monkeypatch.setattr(service_app.subprocess, "Popen", _popen)
    app = service_app.create_app(_corpus(tmp_path))

    resp = _ask_endpoint(app)(name="read", body=_att_body(), request=_stream_request())
    events = [json.loads(l) for c in _drain(resp) for l in c.splitlines() if l.strip()]
    assert len(events) == 1
    assert events[0]["event"] == "error" and events[0]["kind"] == "ask_failed"
    assert "No such file or directory" in events[0]["detail"]
    assert _spilled(spill) == []


# --- a client that leaves mid-stream releases everything --------------------------
# Starlette never closes an abandoned sync body: on a disconnect it cancels the send
# loop and leaves the generator suspended until the cyclic GC finds it, which an idle
# server may never run. The temp files stayed and `mo` kept running. The response
# closes its own body; that close runs _relay's finally.

import subprocess
import pytest
from starlette.requests import ClientDisconnect


class _RunningPopen:
    """A process that has written one line and is still running: its stdout stays open."""
    def __init__(self, wait_raises=False):
        r, self._w = os.pipe()
        os.write(self._w, b'{"event":"token","text":"hi"}\n')
        self.stdout = os.fdopen(r, "rb", buffering=0)
        self.stderr = io.BytesIO(b"")
        self.pid, self.killed, self.waited = 4242, False, False
        self._wait_raises = wait_raises

    def poll(self): return 0 if self.killed else None
    def kill(self): self.killed = True

    def wait(self, timeout=None):
        self.waited = True
        if self._wait_raises:
            raise subprocess.TimeoutExpired("mo", timeout)
        return -9


def _leave_after_first_chunk(resp, observe):
    """Drive the response under ASGI 2.4: the client is gone when the first body chunk is
    sent. `observe` runs while the loop is still alive — a real server's loop never shuts
    down, so the async-generator cleanup at asyncio.run's exit must not count."""
    async def receive():
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.body":
            raise OSError("client went away")

    async def run():
        with pytest.raises(ClientDisconnect):
            await resp({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        return observe()
    return asyncio.run(run())


def _stream_with(tmp_path, monkeypatch, proc):
    spill = tmp_path / "tmp"; spill.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(spill))
    monkeypatch.setattr(service_app.shutil, "which", lambda _: "/usr/bin/mo")
    monkeypatch.setattr(service_app.subprocess, "Popen", lambda cmd, **kw: proc)
    app = service_app.create_app(_corpus(tmp_path))
    return spill, _ask_endpoint(app)(name="read", body=_att_body(), request=_stream_request())


def test_a_client_leaving_mid_stream_kills_reaps_and_cleans(tmp_path, monkeypatch):
    proc = _RunningPopen()
    spill, resp = _stream_with(tmp_path, monkeypatch, proc)
    killed, waited, spilled = _leave_after_first_chunk(
        resp, lambda: (proc.killed, proc.waited, _spilled(spill)))
    assert killed, "the ask the client abandoned is killed"
    assert waited, "a killed ask is reaped, not left a zombie"
    assert spilled == [], "its temp files are gone"


def test_a_killed_ask_that_will_not_die_is_said(tmp_path, monkeypatch, capsys):
    # The 200 is on the wire; the stuck reap is logged, not raised into the response.
    proc = _RunningPopen(wait_raises=True)
    spill, resp = _stream_with(tmp_path, monkeypatch, proc)
    killed, waited, spilled = _leave_after_first_chunk(
        resp, lambda: (proc.killed, proc.waited, _spilled(spill)))
    assert killed and waited
    assert "did not exit" in capsys.readouterr().err
    assert spilled == []
