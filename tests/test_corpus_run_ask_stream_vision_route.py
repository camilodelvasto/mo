# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import base64, hashlib, json
import pytest
from shapes.corpus.access import run_ask, attest

SECRET = b"secret-xyz"

def _att():
    sig = attest.sign(SECRET, "read", hashlib.sha256(b"webp").hexdigest(), "image/webp")
    return {"data": base64.b64encode(b"webp").decode(), "signature": sig, "media_type": "image/webp"}

def _wire(monkeypatch, ask):
    calls = {}
    def _fake_vision(ask, asks, q, passages, mr, g, hist, atts, meta):
        calls["vision"] = True; meta.update(model="v"); yield "seen-image"
    def _fake_text(*a, **k):
        calls["text"] = True; yield "no-image"
    monkeypatch.setattr(run_ask, "_synthesize_stream_vision", _fake_vision)
    monkeypatch.setattr(run_ask, "_synthesize_stream", _fake_text)
    monkeypatch.setattr(run_ask.attest, "load_secret", lambda mr: SECRET)
    # the binding table: each capability declares the wire shape it reads
    monkeypatch.setattr(run_ask.capabilities, "load_table", lambda mr: {"capabilities": {
        "api.claude-vision": {"reads": "envelope", "emits": "envelope", "stream": ["v"]},
        "api.claude-json": {"reads": "stdin", "emits": "envelope", "stream": ["t"]}}})
    # stub the retrieve/reconcile machinery this route touches
    monkeypatch.setattr(run_ask.reconcile, "reconcile", lambda *a, **k: None)
    monkeypatch.setattr(run_ask.askfile, "load_asks", lambda c: {"asks": []})
    monkeypatch.setattr(run_ask.askfile, "resolve_ask", lambda asks, i: ask)
    monkeypatch.setattr(run_ask, "_load_flow", lambda c: {})
    monkeypatch.setattr(run_ask.index, "open_index", lambda c: _FakeConn())
    monkeypatch.setattr(run_ask.flt, "doc_ids_for", lambda *a, **k: set())
    monkeypatch.setattr(run_ask.retrieve, "retrieve_many", lambda *a, **k: [])
    return calls


VISION_ASK = {"id": "read", "attachments": {"accept": ["image"]},
              "synthesize": {"uses": "api.claude-vision", "prompt": "${question}"},
              "retrieve": {"mode": "none"}}


def test_attachments_route_to_vision_stream(monkeypatch):
    calls = _wire(monkeypatch, VISION_ASK)
    events = list(run_ask.run_ask_stream(None, None, "read", "what is this?",
                                         attachments=[_att()]))
    assert calls.get("vision") and "text" not in calls
    assert any(e.get("event") == "token" and e["text"] == "seen-image" for e in events)


def test_attachments_ask_uses_vision_path_even_on_a_text_only_turn(monkeypatch):
    # The ask's synthesize binding is the vision wrapper, which reads a multimodal
    # envelope. A turn with no image must still be shaped as an envelope (zero image
    # blocks), never as a bare prompt the vision binding cannot parse.
    calls = _wire(monkeypatch, VISION_ASK)
    events = list(run_ask.run_ask_stream(None, None, "read", "hello, no image"))
    assert calls.get("vision") and "text" not in calls
    assert not any(e.get("event") == "error" for e in events)


def test_plain_ask_keeps_the_text_path(monkeypatch):
    plain = {"id": "plain", "synthesize": {"uses": "api.claude-json", "prompt": "${question}"},
             "retrieve": {"mode": "none"}}
    calls = _wire(monkeypatch, plain)
    list(run_ask.run_ask_stream(None, None, "plain", "hello"))
    assert calls.get("text") and "vision" not in calls

class _FakeConn:
    def execute(self, *a): return []
    def close(self): pass


def test_attachments_on_a_plain_ask_are_refused_not_dropped(monkeypatch):
    # No policy → no vision binding → the image would be silently ignored by the
    # text path. Refuse loudly instead.
    plain = {"id": "plain", "synthesize": {"uses": "api.claude-json", "prompt": "${question}"},
             "retrieve": {"mode": "none"}}
    calls = _wire(monkeypatch, plain)
    events = list(run_ask.run_ask_stream(None, None, "plain", "look", attachments=[_att()]))
    assert "text" not in calls and "vision" not in calls
    assert events[-1]["event"] == "error" and events[-1]["kind"] == "no_attachments_policy"


def test_max_count_is_enforced_by_the_box_over_the_whole_conversation(monkeypatch):
    # The client pre-checks max_count as a hint; the box is the authority. Two carried
    # images (one in history, one on this turn) against max_count: 1 → too_many.
    capped = dict(VISION_ASK, attachments={"accept": ["image"], "max_count": 1})
    calls = _wire(monkeypatch, capped)
    a1, a2 = _att(), dict(_att(), data=base64.b64encode(b"other").decode())
    a2["signature"] = attest.sign(SECRET, "read", hashlib.sha256(b"other").hexdigest(), "image/webp")
    history = [{"role": "user", "content": "first", "attachments": [a1]},
               {"role": "assistant", "content": "ok"}]
    events = list(run_ask.run_ask_stream(None, None, "read", "second", history=history, attachments=[a2]))
    assert "vision" not in calls and "text" not in calls
    assert events[-1]["event"] == "error" and events[-1]["kind"] == "too_many"


def test_max_count_absent_means_unbounded(monkeypatch):
    calls = _wire(monkeypatch, VISION_ASK)     # accept only, no max_count
    events = list(run_ask.run_ask_stream(None, None, "read", "q", attachments=[_att()]))
    assert calls.get("vision") and not any(e.get("event") == "error" for e in events)


def test_the_current_turn_over_the_envelope_bound_is_refused_without_max_count(monkeypatch):
    # No max_count on the ask, but the envelope carries at most MAX_ENVELOPE_IMAGES:
    # the current turn's images are never dropped, so a turn over the bound is refused.
    calls = _wire(monkeypatch, VISION_ASK)
    atts = []
    for i in range(run_ask.MAX_ENVELOPE_IMAGES + 1):
        raw = b"webp%d" % i
        atts.append({"data": base64.b64encode(raw).decode(), "media_type": "image/webp",
                     "signature": attest.sign(SECRET, "read", hashlib.sha256(raw).hexdigest(), "image/webp")})
    events = list(run_ask.run_ask_stream(None, None, "read", "q", attachments=atts))
    assert "vision" not in calls and "text" not in calls
    assert events[-1]["event"] == "error" and events[-1]["kind"] == "too_many"


def _signed(raw, media_type="image/webp"):
    return {"data": base64.b64encode(raw).decode(), "media_type": media_type,
            "signature": attest.sign(SECRET, "read", hashlib.sha256(raw).hexdigest(), media_type)}


def test_a_reused_signature_with_other_bytes_is_refused(monkeypatch):
    # The history turn is genuine; the current turn replays its signature over other
    # bytes. Dedup by signature must not let the second copy skip verification.
    calls = _wire(monkeypatch, VISION_ASK)
    good = _signed(b"A")
    evil = dict(good, data=base64.b64encode(b"EVIL").decode())
    history = [{"role": "user", "content": "first", "attachments": [good]},
               {"role": "assistant", "content": "ok"}]
    events = list(run_ask.run_ask_stream(None, None, "read", "q", history=history, attachments=[evil]))
    assert "vision" not in calls and "text" not in calls
    assert events[-1]["event"] == "error" and events[-1]["kind"] == "attachment_untrusted"


def test_a_reused_signature_with_another_media_type_is_refused(monkeypatch):
    calls = _wire(monkeypatch, VISION_ASK)
    good = _signed(b"A")
    swapped = dict(good, media_type="image/png")
    history = [{"role": "user", "content": "first", "attachments": [good]},
               {"role": "assistant", "content": "ok"}]
    events = list(run_ask.run_ask_stream(None, None, "read", "q", history=history, attachments=[swapped]))
    assert "vision" not in calls and "text" not in calls
    assert events[-1]["event"] == "error" and events[-1]["kind"] == "attachment_untrusted"


def test_a_token_issued_under_another_ask_is_refused(monkeypatch):
    # Signed by the box under ask "other" (whose policy may be looser); sent to "read".
    calls = _wire(monkeypatch, VISION_ASK)
    foreign = dict(_signed(b"A"), signature=attest.sign(
        SECRET, "other", hashlib.sha256(b"A").hexdigest(), "image/webp"))
    events = list(run_ask.run_ask_stream(None, None, "read", "q", attachments=[foreign]))
    assert "vision" not in calls and "text" not in calls
    assert events[-1]["event"] == "error" and events[-1]["kind"] == "attachment_untrusted"


@pytest.mark.parametrize("roles", [
    ["user"],                                  # ends on the user: user,user with this turn
    ["assistant", "user", "assistant"],        # opens with the assistant
    ["user", "user", "assistant"],             # a user,user pair mid-history
    ["user", "assistant", "assistant"],
])
def test_history_that_does_not_alternate_is_refused(monkeypatch, roles):
    calls = _wire(monkeypatch, VISION_ASK)
    history = [{"role": r, "content": "t%d" % i} for i, r in enumerate(roles)]
    events = list(run_ask.run_ask_stream(None, None, "read", "q", history=history))
    assert "vision" not in calls and "text" not in calls
    assert events[-1]["event"] == "error" and events[-1]["kind"] == "history_malformed"


def test_an_assistant_turn_carrying_attachments_is_refused_naming_the_turn(monkeypatch):
    # Images belong to the user's turns; the provider rejects them on the assistant's.
    calls = _wire(monkeypatch, VISION_ASK)
    history = [{"role": "user", "content": "t0"},
               {"role": "assistant", "content": "t1", "attachments": [_att()]}]
    events = list(run_ask.run_ask_stream(None, None, "read", "q", history=history))
    assert "vision" not in calls and "text" not in calls
    assert events[-1]["event"] == "error" and events[-1]["kind"] == "history_malformed"
    assert "turn 1" in events[-1]["detail"]
