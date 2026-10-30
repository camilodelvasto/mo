# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from cli.infra.services import resolve_chat_binding, ChatBindingError

GROVE = {"features": [{"type": "chat", "id": "assistant", "ask": "converse"},
                      {"type": "chat", "id": "explorar", "ask": "explorar"}]}


def _box_target(envs):  # a corpus-server target dict
    return {"stack": "corpus-server", "environments": envs}


def test_no_services_chat_throws_named(tmp_path):
    env = {"remote": "github/moui-grove"}              # grove env, no services.chat
    with pytest.raises(ChatBindingError, match="no services.chat"):
        resolve_chat_binding(GROVE, env, "prod", tmp_path)


def test_missing_box_target_throws_named(tmp_path, monkeypatch):
    from cli.infra import services
    monkeypatch.setattr(services, "load_target",
                        lambda ref, root: (_ for _ in ()).throw(services.TargetError("no such target")))
    env = {"services": {"chat": "corpus-server/acme"}, "credential": "secrets/x.yaml"}
    with pytest.raises(ChatBindingError, match="no such target|corpus-server/acme"):
        resolve_chat_binding(GROVE, env, "prod", tmp_path)


def test_no_matching_env_throws_named(tmp_path, monkeypatch):
    from cli.infra import services
    monkeypatch.setattr(services, "load_target", lambda ref, root: _box_target({"prod": {"domain": "ask.moui.co"}}))
    env = {"services": {"chat": "corpus-server/acme"}, "credential": "secrets/x.yaml"}
    with pytest.raises(ChatBindingError, match="staging"):
        resolve_chat_binding(GROVE, env, "staging", tmp_path)   # box has only prod


def test_happy_resolution(tmp_path, monkeypatch):
    from cli.infra import services
    monkeypatch.setattr(services, "load_target", lambda ref, root: _box_target(
        {"prod": {"domain": "ask.moui.co", "auth": {"scheme": "access-code"}}}))
    monkeypatch.setattr(services, "_read_secret_code",
                        lambda path, root: "TESTCODE123")
    env = {"services": {"chat": "corpus-server/acme"},
           "credential": "secrets/corpus-server/hub-web.yaml"}
    b = resolve_chat_binding(GROVE, env, "prod", tmp_path)
    assert b["endpoint"] == "https://ask.moui.co/api"
    assert b["code"] == "TESTCODE123"
    assert b["gate"] == {"scheme": "access-code", "check": "https://ask.moui.co/api/check"}
    assert "auth" not in b
    # one value → both sinks: every CSP origin is origin_of(endpoint)
    assert b["feature_endpoints"] == {"assistant": "https://ask.moui.co",
                                      "explorar": "https://ask.moui.co"}


def test_gate_block_derived_for_access_code(tmp_path, monkeypatch):
    from cli.infra import services
    monkeypatch.setattr(services, "load_target", lambda ref, root: _box_target(
        {"prod": {"domain": "ask.moui.co", "auth": {"scheme": "access-code"}}}))
    monkeypatch.setattr(services, "_read_secret_code", lambda path, root: "PROBECODE")
    env = {"services": {"chat": "corpus-server/moui"},
           "credential": "secrets/corpus-server/moui-web.yaml"}
    b = resolve_chat_binding(GROVE, env, "prod", tmp_path)
    assert b["endpoint"] == "https://ask.moui.co/api"
    assert b["gate"] == {"scheme": "access-code", "check": "https://ask.moui.co/api/check"}
    assert b["code"] == "PROBECODE"          # held for the probe, not for the page
    assert "auth" not in b                    # the seam: auth stops at the resolver


def test_no_gate_block_when_scheme_none(tmp_path, monkeypatch):
    from cli.infra import services
    monkeypatch.setattr(services, "load_target", lambda ref, root: _box_target(
        {"prod": {"domain": "ask.moui.co", "auth": {"scheme": "none"}}}))
    env = {"services": {"chat": "corpus-server/moui"}}   # no credential needed when open
    b = resolve_chat_binding(GROVE, env, "prod", tmp_path)
    assert b["gate"] is None and b["code"] is None
    assert b["endpoint"] == "https://ask.moui.co/api"


def test_missing_secret_throws(tmp_path, monkeypatch):
    from cli.infra import services
    monkeypatch.setattr(services, "load_target", lambda ref, root: _box_target(
        {"prod": {"domain": "ask.moui.co", "auth": {"scheme": "access-code"}}}))
    monkeypatch.setattr(services, "_read_secret_code",
                        lambda path, root: (_ for _ in ()).throw(
                            ChatBindingError(f"chat credential secret not found: {path} — "
                                             f"create it (it holds the access code; gitignored, never committed)")))
    env = {"services": {"chat": "corpus-server/acme"}, "credential": "secrets/missing.yaml"}
    with pytest.raises(ChatBindingError, match="chat credential secret not found"):
        resolve_chat_binding(GROVE, env, "prod", tmp_path)


def test_with_code_false_skips_secret_read(tmp_path, monkeypatch):
    from cli.infra import services
    monkeypatch.setattr(services, "load_target", lambda ref, root: _box_target(
        {"local": {"domain": "api.local.test", "auth": {"scheme": "access-code"}}}))
    # No credential key, and _read_secret_code would raise if called.
    def _boom(path, root):
        raise AssertionError("secret read must not happen when with_code=False")
    monkeypatch.setattr(services, "_read_secret_code", _boom)
    env = {"services": {"chat": "corpus-server/moui"}}        # no credential key
    b = resolve_chat_binding(GROVE, env, "local", tmp_path, with_code=False)
    assert b["endpoint"] == "https://api.local.test/api"
    assert b["gate"] == {"scheme": "access-code", "check": "https://api.local.test/api/check"}
    assert b["code"] is None


# --- persist: local needs a titled ask --------------------------------------------
# The client names (and therefore stores) a conversation from the box's `title` event,
# which only a `titled: true` ask emits. A persist: local chat on an untitled ask
# looks like it works and silently stores nothing. The binding is where the grove and
# the box meet, so the mismatch is caught there — at build, not in a visitor's browser.

PERSIST_GROVE = {"features": [{"type": "chat", "id": "mira", "ask": "mira", "persist": "local"}]}


def _box_with_asks(tmp_path, asks):
    import yaml
    content = tmp_path / "content" / "c"; content.mkdir(parents=True)
    (content / "ask.yaml").write_text(yaml.safe_dump({"id": "c", "version": 1, "asks": asks}))
    return _box_target({"prod": {"domain": "ask.test", "auth": {"scheme": "none"},
                                 "content": "content/c"}})


def test_persist_local_on_an_untitled_ask_is_refused(tmp_path, monkeypatch):
    from cli.infra import services
    box = _box_with_asks(tmp_path, [{"id": "mira", "synthesize": {"uses": "x", "prompt": "p"}}])
    monkeypatch.setattr(services, "load_target", lambda ref, root: box)
    env = {"services": {"chat": "corpus-server/c"}, "credential": "secrets/x.yaml"}
    with pytest.raises(ChatBindingError, match="titled"):
        resolve_chat_binding(PERSIST_GROVE, env, "prod", tmp_path, with_code=False)


def test_persist_local_on_a_titled_ask_resolves(tmp_path, monkeypatch):
    from cli.infra import services
    box = _box_with_asks(tmp_path, [{"id": "mira", "synthesize": {"uses": "x", "prompt": "p", "titled": True}}])
    monkeypatch.setattr(services, "load_target", lambda ref, root: box)
    env = {"services": {"chat": "corpus-server/c"}, "credential": "secrets/x.yaml"}
    assert resolve_chat_binding(PERSIST_GROVE, env, "prod", tmp_path, with_code=False)["endpoint"]


def test_persist_none_needs_no_title(tmp_path, monkeypatch):
    from cli.infra import services
    box = _box_with_asks(tmp_path, [{"id": "mira", "synthesize": {"uses": "x", "prompt": "p"}}])
    monkeypatch.setattr(services, "load_target", lambda ref, root: box)
    grove = {"features": [{"type": "chat", "id": "mira", "ask": "mira", "persist": "none"}]}
    env = {"services": {"chat": "corpus-server/c"}, "credential": "secrets/x.yaml"}
    assert resolve_chat_binding(grove, env, "prod", tmp_path, with_code=False)["endpoint"]


def test_a_box_env_without_content_cannot_be_checked_and_says_so(tmp_path, monkeypatch):
    from cli.infra import services
    monkeypatch.setattr(services, "load_target", lambda ref, root: _box_target(
        {"prod": {"domain": "ask.test", "auth": {"scheme": "none"}}}))
    env = {"services": {"chat": "corpus-server/c"}, "credential": "secrets/x.yaml"}
    with pytest.raises(ChatBindingError, match="content"):
        resolve_chat_binding(PERSIST_GROVE, env, "prod", tmp_path, with_code=False)
