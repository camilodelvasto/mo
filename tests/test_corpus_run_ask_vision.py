# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import base64
import hashlib

import pytest

from shapes.corpus.access import run_ask, attest
from shapes.corpus.access.errors import AttachmentError

SECRET = b"secret-xyz"

def _att(png=b"\x89PNGdata"):
    canonical = png
    sig = attest.sign(SECRET, "read", hashlib.sha256(canonical).hexdigest(), "image/webp")
    return {"data": base64.b64encode(canonical).decode(),
            "signature": sig, "media_type": "image/webp"}

def _load_secret_ok(monkeypatch):
    monkeypatch.setattr(run_ask.attest, "load_secret", lambda mr: SECRET)

def test_verify_attachments_accepts_signed(monkeypatch):
    _load_secret_ok(monkeypatch)
    run_ask._verify_attachments(None, "read", [_att()])       # no raise

def test_verify_attachments_rejects_tampered(monkeypatch):
    _load_secret_ok(monkeypatch)
    bad = _att(); bad["data"] = base64.b64encode(b"other").decode()
    with pytest.raises(AttachmentError) as e:
        run_ask._verify_attachments(None, "read", [bad])
    assert e.value.kind == "attachment_untrusted"

def test_build_vision_envelope_places_images_and_system():
    ask = {"synthesize": {"uses": "api.claude-vision", "prompt": "Answer: ${question}"}}
    env = run_ask._build_vision_envelope(
        ask, {}, "what is this?", [], 1.0,
        history=[{"role": "user", "content": "earlier", "attachments": [_att()]},
                 {"role": "assistant", "content": "ok"}],
        attachments=[_att()])
    assert "system" in env and isinstance(env["messages"], list)
    # current turn is last, carries the question text + one image block
    last = env["messages"][-1]
    assert last["role"] == "user"
    kinds = [b["type"] for b in last["content"]]
    assert kinds[0] == "text" and "image" in kinds
    assert "what is this?" in last["content"][0]["text"]
    # a history user turn also carries its image
    first = env["messages"][0]
    assert any(b["type"] == "image" for b in first["content"])

def test_collect_attachments_dedupes_by_signature():
    a = _att()
    got = run_ask._collect_attachments(
        [{"role": "user", "content": "x", "attachments": [a]}], [a])
    assert len(got) == 1


def _passage():
    return [{"doc_id": "abc123def456", "ref": "0", "text": "the sky is blue",
             "name": "sky.md"}]


def test_vision_envelope_retrieved_placeholder_substitutes_into_prompt():
    """When ${retrieved} appears in the prompt, passages go there — NOT also
    into the system block. No literal ${retrieved} token should survive."""
    ask = {"synthesize": {"uses": "api.claude-vision",
                          "prompt": "Context: ${retrieved}\nQ: ${question}"}}
    passages = _passage()
    env = run_ask._build_vision_envelope(ask, {}, "hue?", passages, 1.0, [], [_att()])
    last_text = env["messages"][-1]["content"][0]["text"]
    # (a) passages are in the prompt
    assert "the sky is blue" in last_text
    # (a) passages are NOT also in the system block (no duplication)
    assert "the sky is blue" not in env["system"]
    # (b) no literal placeholder tokens remain in prompt or system
    assert "${retrieved}" not in last_text
    assert "${retrieved}" not in env["system"]
    assert "${history}" not in last_text
    assert "${history}" not in env["system"]


def test_vision_envelope_no_retrieved_placeholder_injects_into_system():
    """When ${retrieved} is absent, the engine injects passages into the system
    block (same as the text path). The prompt must not contain the raw token."""
    ask = {"synthesize": {"uses": "api.claude-vision", "prompt": "Q: ${question}"}}
    passages = _passage()
    env = run_ask._build_vision_envelope(ask, {}, "hue?", passages, 1.0, [], [_att()])
    # passages go to system
    assert "the sky is blue" in env["system"]
    # not duplicated in the prompt
    last_text = env["messages"][-1]["content"][0]["text"]
    assert "the sky is blue" not in last_text
    # no stray placeholder tokens
    assert "${retrieved}" not in last_text
    assert "${history}" not in last_text


def test_vision_envelope_history_placeholder_removed():
    """${history} in a vision prompt is substituted with an empty string because
    history is represented structurally as messages, not as inline text."""
    ask = {"synthesize": {"uses": "api.claude-vision",
                          "prompt": "History: ${history}\nQ: ${question}"}}
    env = run_ask._build_vision_envelope(ask, {}, "hue?", [], 1.0, [], [_att()])
    last_text = env["messages"][-1]["content"][0]["text"]
    assert "${history}" not in last_text
    # the placeholder is simply removed, not replaced with something else
    assert "History: \n" in last_text or "History:  " in last_text or "History: \nQ:" in last_text


# --- the envelope is bounded, like the text path ----------------------------------
# The text path trims history to HISTORY_BUDGET_CHARS. The vision path represents the
# conversation structurally, so it needs the same bound in its own terms: the oldest
# whole turns drop, and an image is worth far more than its text.

_ASK = {"synthesize": {"uses": "api.claude-vision", "prompt": "${question}"}}


def _turn(role, text, n_images=0):
    atts = [{"data": "aW1n", "signature": "s%d" % i, "media_type": "image/webp"} for i in range(n_images)]
    t = {"role": role, "content": text}
    if atts:
        t["attachments"] = atts
    return t


def test_vision_history_drops_oldest_whole_turns_over_the_char_budget():
    long_turn = "x" * (run_ask.HISTORY_BUDGET_CHARS // 2)
    history = [_turn("user", "oldest " + long_turn), _turn("assistant", "a " + long_turn),
               _turn("user", "newest " + long_turn), _turn("assistant", "ok")]
    env = run_ask._build_vision_envelope(_ASK, {}, "q", [], 0.5, history, [])
    texts = ["".join(b["text"] for b in m["content"] if b["type"] == "text") for m in env["messages"]]
    assert not any(t.startswith("oldest") for t in texts), "the oldest whole turn is dropped"
    assert any(t.startswith("newest") for t in texts)
    assert texts[-1] == "q", "the current question is always the last message"


def test_vision_history_keeps_at_most_max_images_newest_first():
    # Six history turns carrying three images each, plus one on this turn: far over
    # the bound. The newest whole turns survive, the oldest drop.
    history = []
    for i in range(6):
        history.append(_turn("user", "turn%d" % i, 3))
        history.append(_turn("assistant", "ok%d" % i))
    env = run_ask._build_vision_envelope(_ASK, {}, "q", [], 0.5, history,
                                         [{"data": "Y3Vy", "signature": "cur", "media_type": "image/webp"}])
    images = [b for m in env["messages"] for b in m["content"] if b["type"] == "image"]
    assert len(images) <= run_ask.MAX_ENVELOPE_IMAGES, "the envelope is bounded"
    texts = ["".join(b["text"] for b in m["content"] if b["type"] == "text") for m in env["messages"]]
    assert "turn0" not in texts and "turn5" in texts, "oldest dropped, newest kept"
    assert images[-1]["data"] == "Y3Vy", "this turn's image is last"


def test_the_current_turns_images_are_never_dropped():
    # Whatever the history costs, the images this turn carries are the question.
    history = [_turn("user", "old", run_ask.MAX_ENVELOPE_IMAGES + 3), _turn("assistant", "a")]
    current = [{"data": "Y3Vy", "signature": "cur", "media_type": "image/webp"}]
    env = run_ask._build_vision_envelope(_ASK, {}, "q", [], 0.5, history, current)
    last = env["messages"][-1]["content"]
    assert [b for b in last if b["type"] == "image"] == [
        {"type": "image", "media_type": "image/webp", "data": "Y3Vy"}]


_CUR = {"data": "Y3Vy", "signature": "cur", "media_type": "image/webp"}


def test_an_image_cut_never_leaves_the_envelope_opening_with_the_assistant():
    # 5 x (user with 2 images, assistant) + 1 current image: the image bound cuts on a
    # user turn. The provider refuses a conversation that opens with the assistant.
    history = []
    for i in range(5):
        history.append(_turn("user", "u%d" % i, 2))
        history.append(_turn("assistant", "a%d" % i))
    env = run_ask._build_vision_envelope(_ASK, {}, "q", [], 0.5, history, [_CUR])
    assert env["messages"][0]["role"] == "user"
    assert _texts(env)[:-1] == ["u2", "a2", "u3", "a3", "u4", "a4"]


def test_a_char_cut_never_leaves_the_envelope_opening_with_the_assistant():
    half = run_ask.HISTORY_BUDGET_CHARS // 2
    history = [_turn("user", "u" * (half + 10)), _turn("assistant", "a" * half),
               _turn("user", "short"), _turn("assistant", "ok")]
    env = run_ask._build_vision_envelope(_ASK, {}, "q", [], 0.5, history, [])
    assert env["messages"][0]["role"] == "user"
    assert _texts(env)[:-1] == ["short", "ok"]


def test_the_image_bound_holds_even_for_the_newest_history_turn():
    # The newest user turn is over the bound on its own: no exception keeps it.
    history = [_turn("user", "u0"), _turn("assistant", "a0"),
               _turn("user", "old", run_ask.MAX_ENVELOPE_IMAGES + 3), _turn("assistant", "a1")]
    env = run_ask._build_vision_envelope(_ASK, {}, "q", [], 0.5, history, [_CUR])
    images = [b for m in env["messages"] for b in m["content"] if b["type"] == "image"]
    assert len(images) <= run_ask.MAX_ENVELOPE_IMAGES

    assert _texts(env) == ["q"], "the over-bound turn and every older one drop; a lone assistant turn cannot open"


def _texts(env):
    return ["".join(b["text"] for b in m["content"] if b["type"] == "text") for m in env["messages"]]


def test_the_envelope_strictly_alternates_opening_and_closing_on_the_user():
    history = []
    for i in range(6):
        history.append(_turn("user", "u%d" % i, 2))
        history.append(_turn("assistant", "a%d" % i))
    env = run_ask._build_vision_envelope(_ASK, {}, "q", [], 0.5, history, [_CUR])
    roles = [m["role"] for m in env["messages"]]
    assert roles[0] == "user" and roles[-1] == "user"
    assert all(a != b for a, b in zip(roles, roles[1:])), roles


def test_every_attachment_is_verified_not_one_per_signature(monkeypatch):
    # Same signature, different bytes: the second copy must be verified on its own.
    _load_secret_ok(monkeypatch)
    good = _att()
    evil = dict(good, data=base64.b64encode(b"EVIL").decode())
    with pytest.raises(AttachmentError) as e:
        run_ask._verify_attachments(None, "read", run_ask._envelope_attachments(
            [{"role": "user", "content": "x", "attachments": [good]},
             {"role": "assistant", "content": "ok"}], [evil]))
    assert e.value.kind == "attachment_untrusted"

def test_a_non_ascii_signature_is_untrusted_not_a_crash(monkeypatch):
    _load_secret_ok(monkeypatch)
    bad = dict(_att(), signature="é")
    with pytest.raises(AttachmentError) as exc:
        run_ask._verify_attachments(None, "read", [bad])
    assert exc.value.kind == "attachment_untrusted"

def test_junk_after_valid_base64_is_untrusted_not_silently_dropped(monkeypatch):
    # Lenient decoding drops "!!" and verifies the signed bytes, while the client's raw
    # string — junk included — is what reaches the provider. The string verified must
    # be the string forwarded.
    _load_secret_ok(monkeypatch)
    bad = _att(); bad["data"] += "!!"
    with pytest.raises(AttachmentError) as e:
        run_ask._verify_attachments(None, "read", [bad])
    assert e.value.kind == "attachment_untrusted"
