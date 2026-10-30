# tests/test_corpus_service_verify.py
import io
import pytest
import sys
from pathlib import Path

import yaml
from fastapi.testclient import TestClient
from PIL import Image

from shapes.corpus.service import app as service_app

def _corpus(tmp_path: Path) -> Path:
    (tmp_path / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\nask: ./ask.yaml\n")
    (tmp_path / "flow.yaml").write_text("pipeline: []\n")
    asks = {"id": "c", "version": 1, "asks": [
        {"id": "read", "attachments": {"accept": ["image"], "max_count": 2, "max_bytes": 10_000_000},
         "synthesize": {"uses": "api.claude-vision", "prompt": "${question}"}},
        {"id": "plain", "synthesize": {"uses": "api.claude-json", "prompt": "${question}"}}]}
    (tmp_path / "ask.yaml").write_text(yaml.safe_dump(asks))
    return tmp_path

def _machine(tmp_path: Path, concurrency: int = 2) -> Path:
    mr = tmp_path / "machine"; mr.mkdir()
    (mr / "attest.secret").write_text("secret-xyz")
    (mr / "capabilities.yaml").write_text(
        f"capabilities:\n  media.image:\n    run: [{sys.executable}, bin/image-canonicalize, "
        "--max-edge, '2048', --quality, '82', --max-pixels, '40000000']\n"
        f"    reads: stdin\n    emits: stdout\n    timeout: 60\n    concurrency: {concurrency}\n")
    return mr

def _jpeg() -> bytes:
    buf = io.BytesIO(); Image.new("RGB", (48, 48), (1, 2, 3)).save(buf, format="JPEG")
    return buf.getvalue()

def _client(tmp_path, monkeypatch, concurrency: int = 2):
    # The ask/policy + verify routes must not require the full cache/flow machinery.
    # Point the app at a corpus dir + machine root; reuse create_app.
    corpus = _corpus(tmp_path); mr = _machine(tmp_path, concurrency)
    app = service_app.create_app(corpus, machine_root=mr)
    return TestClient(app)

def test_policy_returns_attachments(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/ask/read/policy")
    assert r.status_code == 200
    assert r.json()["attachments"]["accept"] == ["image"]

def test_policy_is_null_for_plain_ask(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/ask/plain/policy").json()["attachments"] is None

def test_policy_unknown_ask_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/ask/nope/policy").status_code == 404

def test_verify_returns_signed_artifact(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/verify/read", content=_jpeg(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["media_type"] == "image/webp" and body["signature"] and body["data"]

def test_verify_oversized_is_413(tmp_path, monkeypatch):
    # A 1-byte policy makes any real image too large; assert the named status.
    c = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(service_app, "_ask_policy",
                        lambda corpus_dir, name: {"accept": ["image"], "max_bytes": 1})
    r = c.post("/verify/read", content=_jpeg(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 413

def test_verify_on_plain_ask_409(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/verify/plain", content=_jpeg(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 409   # ask declares no attachments policy


# --- the body is bounded BEFORE it is buffered ------------------------------------
# /verify is unmetered (a valid code may call it freely). Reading the whole body and
# only then comparing to max_bytes lets one request take the box's memory. The
# declared length is checked first; a request that declares none is refused.

def test_declared_length_over_max_bytes_is_413_without_reading_the_body(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    seen = {}
    async def _never(self):
        seen["read"] = True; return b""
    monkeypatch.setattr(service_app.Request, "body", _never)
    r = c.post("/verify/read", content=b"x" * 16, headers={"Content-Type": "image/jpeg",
                                                            "Content-Length": "99999999999"})
    assert r.status_code == 413 and "read" not in seen


def test_missing_content_length_is_411(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    def chunks():
        yield _jpeg()
    r = c.post("/verify/read", content=chunks(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 411
    assert "length" in r.json()["detail"].lower()


def test_check_declared_length_is_pure_and_named():
    from shapes.corpus.access.errors import AttachmentError
    with pytest.raises(AttachmentError) as e:
        service_app._check_declared_length({}, {"accept": ["image"], "max_bytes": 10})
    assert e.value.kind == "length_required"
    with pytest.raises(AttachmentError) as e:
        service_app._check_declared_length({"content-length": "11"}, {"accept": ["image"], "max_bytes": 10})
    assert e.value.kind == "too_large"
    with pytest.raises(AttachmentError) as e:
        service_app._check_declared_length({"content-length": "abc"}, {"accept": ["image"], "max_bytes": 10})
    assert e.value.kind == "length_required"
    service_app._check_declared_length({"content-length": "10"}, {"accept": ["image"], "max_bytes": 10})
    service_app._check_declared_length({"content-length": "10"}, {"accept": ["image"]})   # no declared bound


def test_a_request_without_a_content_type_is_refused_as_such(tmp_path, monkeypatch):
    # Not "octet-stream, which then fails the accept check" — the absence is its own
    # named refusal (no declared type is not a type).
    c = _client(tmp_path, monkeypatch)
    r = c.post("/verify/read", content=_jpeg(), headers={"Content-Type": ""})
    assert r.status_code == 400 and "content-type" in r.json()["detail"].lower()


def test_verify_runs_off_the_event_loop(tmp_path, monkeypatch):
    seen = {}
    def fake(mr, ask_id, policy, raw, declared_type):
        seen["ask_id"] = ask_id
        import asyncio
        try:
            asyncio.get_running_loop(); seen["on_loop"] = True
        except RuntimeError:
            seen["on_loop"] = False
        return {"data": "", "signature": "", "media_type": "image/webp", "bytes": 0}
    monkeypatch.setattr(service_app.verify_media, "verify_and_sign", fake)
    c = _client(tmp_path, monkeypatch)
    r = c.post("/verify/read", content=_jpeg(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200 and seen["on_loop"] is False
    assert seen["ask_id"] == "read"            # the token names the ask that verified it


def test_a_misbound_media_image_is_a_500_naming_the_binding(tmp_path, monkeypatch):
    from shapes.corpus.engine.errors import CapabilityError
    def fake(*a):
        raise CapabilityError("media.image must declare reads: stdin (got 'envelope')")
    monkeypatch.setattr(service_app.verify_media, "verify_and_sign", fake)
    c = _client(tmp_path, monkeypatch)
    r = c.post("/verify/read", content=_jpeg(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 500 and "media.image" in r.text


# /verify admits at most the binding's declared concurrency; past it, it REFUSES at
# once (503) instead of queueing ~300 MB decodes on the threadpool every sync handler
# shares.
def test_verify_refuses_past_the_declared_concurrency(tmp_path, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    def fake(mr, ask_id, policy, raw, declared_type):
        entered.set()
        assert release.wait(5)
        return {"data": "", "signature": "", "media_type": "image/webp", "bytes": 0}
    monkeypatch.setattr(service_app.verify_media, "verify_and_sign", fake)
    c = _client(tmp_path, monkeypatch, concurrency=1)
    post = lambda: c.post("/verify/read", content=_jpeg(), headers={"Content-Type": "image/jpeg"})
    first = {}
    t = threading.Thread(target=lambda: first.update(r=post()))
    t.start()
    try:
        assert entered.wait(5)
        r = post()                                    # the first is still in flight
        assert r.status_code == 503 and "1 in flight" in r.json()["detail"]
    finally:
        release.set(); t.join(10)
    assert first["r"].status_code == 200
    entered.clear()
    assert post().status_code == 200                  # the slot came back


def test_a_missing_secret_is_a_500_naming_it(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    (c.app.state.machine_root / "attest.secret").unlink()
    r = c.post("/verify/read", content=_jpeg(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 500 and "attest secret" in r.json()["detail"]


def test_an_unknown_attachment_kind_is_not_silently_a_400():
    import inspect
    assert "_VERIFY_STATUS.get(" not in inspect.getsource(service_app)


# The slot bounds DECODES, not uploads: a slow upload (1 byte/s under a large declared
# length) must not hold a slot for the whole transfer and 503 every other /verify.
def test_a_body_still_being_read_holds_no_verify_slot(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, concurrency=1)
    post = lambda: c.post("/verify/read", content=_jpeg(), headers={"Content-Type": "image/jpeg"})
    assert post().status_code == 200                  # the slots now exist
    slots, _ = c.app.state.verify_slots
    real_body, seen = service_app.Request.body, {}
    async def _reading(self):
        seen["free"] = slots.acquire(blocking=False)
        if seen["free"]:
            slots.release()
        return await real_body(self)
    monkeypatch.setattr(service_app.Request, "body", _reading)
    assert post().status_code == 200
    assert seen["free"] is True
