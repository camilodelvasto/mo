# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Recording test: resolve → build-with-binding → probe → adapter.deploy order.

Mocks the four seams already used in test_deploy.py:
  _resolve_deploy, _load_shape_build, _load_adapter
plus the three new names patched onto the deploy module:
  resolve_chat_binding, probe_chat
"""
from pathlib import Path
import types

import pytest
import yaml

import cli.commands.deploy as deploy_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_corpus(tmp_path: Path) -> Path:
    """Minimal corpus that satisfies moui.json + content dir expectations."""
    (tmp_path / "moui.json").write_text("{}")
    content_dir = tmp_path / "content" / "clients" / "acme" / "hub"
    content_dir.mkdir(parents=True)
    # grove.yaml with one chat feature
    grove = {
        "title": "Hub Acme",
        "features": [{"id": "assistant", "type": "chat"}],
    }
    (content_dir / "grove.yaml").write_text(yaml.dump(grove))
    return tmp_path


def _fake_resolve_deploy(corpus_root, content_path, env_name):
    """Stand-in for _resolve_deploy: returns a grove target + prod env."""
    target = {"shape": "grove", "content": "clients/acme/hub"}
    env = {
        "domain": "example.github.io",
        "base_path": "/acme",
        "remote": "gh/acme",
        "publish_path": "/",
        "encrypted": False,
        "crawlable": True,
        "services": {"chat": "corpus-server/acme"},
        "credential": "secrets/acme-chat.yaml",
    }
    remote = {
        "adapter": "github_pages",
        "repo": "git@github.com:example/acme.git",
        "branch": "pages",
        "git_user": "bot",
        "git_email": "bot@moui.co",
        "credential": "ssh-agent",
        "service_worker": True,
    }
    base_url = "https://example.github.io/acme/"
    return target, env, remote, base_url


def _fake_resolve_spine(corpus_root, ref, env_name):
    """Stand-in for _resolve_spine: returns a grove target + prod env (no base_url)."""
    target, env, remote, _ = _fake_resolve_deploy(corpus_root, ref, env_name)
    return {**target, "environments": {env_name: env}}, env, remote


def _make_build_mod(calls: list) -> types.ModuleType:
    """Fake build module whose build() accepts feature_endpoints + chat_config."""
    mod = types.ModuleType("grove_build")

    def build(content_path, instance_name, corpus_root, *,
              encrypted=False, mnemonic=None, rotate=False,
              base_url=None, service_worker=True, local_first=False,
              on_clear="reload", crawlable=True,
              feature_endpoints=None, chat_config=None):
        calls.append(("build", feature_endpoints, chat_config))
        return (Path("/tmp/fake-build-dir"), None)

    mod.build = build
    return mod


def _make_adapter_mod(calls: list) -> types.ModuleType:
    """Fake adapter whose deploy() records a call and returns a URL."""
    mod = types.ModuleType("github_pages")

    def deploy(build_dir, config, publish_path, *, force=False, spa=False):
        calls.append("adapter")
        from shapes.shared.adapters.outcome import Live
        return Live("https://example.github.io/acme/")

    mod.deploy = deploy
    mod.REQUIRES = ()
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_resolve_thread_probe_order(monkeypatch, tmp_path):
    """Asserts resolve → build(with binding) → probe → adapter.deploy order."""
    calls = []
    corpus = _make_corpus(tmp_path)
    content_dir = corpus / "content" / "clients" / "acme" / "hub"

    binding_result = {
        "endpoint": "https://ask.moui.co/api",
        "gate": {"scheme": "access-code", "check": "https://ask.moui.co/api/check"},
        "code": "PROBECODE",
        "feature_endpoints": {"assistant": "https://ask.moui.co"},
    }

    # Patch the four seams on the deploy module
    monkeypatch.setattr(deploy_mod, "_resolve_spine", _fake_resolve_spine)
    monkeypatch.setattr(deploy_mod, "_load_shape_build",
                        lambda cr, sn: _make_build_mod(calls))
    monkeypatch.setattr(deploy_mod, "_load_adapter",
                        lambda cr, an: _make_adapter_mod(calls))

    def fake_resolve_chat_binding(grove, grove_env, env_name, corpus_root):
        calls.append("resolve")
        return binding_result

    monkeypatch.setattr(deploy_mod, "resolve_chat_binding", fake_resolve_chat_binding)

    probe_args = []

    def fake_probe_chat(endpoint, grove_origin, code, **kw):
        probe_args.append((endpoint, grove_origin, code))
        calls.append(f"probe:{grove_origin}")

    monkeypatch.setattr(deploy_mod, "probe_chat", fake_probe_chat)

    # Also stub out resolve_credentials so it doesn't need real infra
    monkeypatch.setattr(deploy_mod, "resolve_credentials",
                        lambda remote, name, cr: {})

    deploy_mod.run(corpus, None, [str(content_dir), "prod"])

    # ORDER matters: resolve before build, probe after build, adapter last
    assert calls[0] == "resolve"
    build_idx = next(i for i, c in enumerate(calls) if isinstance(c, tuple) and c[0] == "build")
    probe_idx = next(i for i, c in enumerate(calls) if isinstance(c, str) and c.startswith("probe:"))
    adapter_idx = calls.index("adapter")

    assert calls[0] == "resolve"
    assert build_idx > 0
    assert probe_idx > build_idx
    assert adapter_idx > probe_idx

    # Probe received the grove origin derived from base_url
    assert f"probe:https://example.github.io" in calls

    # build() received feature_endpoints and chat_config — NO code in chat_config
    build_call = next(c for c in calls if isinstance(c, tuple) and c[0] == "build")
    _, feature_endpoints, chat_config = build_call
    assert feature_endpoints == {"assistant": "https://ask.moui.co"}
    assert chat_config == {"endpoint": "https://ask.moui.co/api",
                           "gate": {"scheme": "access-code",
                                    "check": "https://ask.moui.co/api/check"}}
    assert "code" not in chat_config

    # Probe was called with the check URL + grove origin + code (not the endpoint)
    probe_call = probe_args[0]
    assert probe_call == ("https://ask.moui.co/api/check",
                          "https://example.github.io", "PROBECODE")


def test_no_chat_features_skips_resolve_and_probe(monkeypatch, tmp_path):
    """When the grove has no chat features, resolve_chat_binding and probe_chat
    must NOT be called and the build must receive no chat kwargs."""
    calls = []
    corpus = _make_corpus(tmp_path)

    # Overwrite grove.yaml — no chat features
    content_dir = corpus / "content" / "clients" / "acme" / "hub"
    (content_dir / "grove.yaml").write_text(yaml.dump({
        "title": "No Chat Grove",
        "features": [{"id": "nav", "type": "navigation"}],
    }))

    monkeypatch.setattr(deploy_mod, "_resolve_spine", _fake_resolve_spine)
    monkeypatch.setattr(deploy_mod, "_load_shape_build",
                        lambda cr, sn: _make_build_mod(calls))
    monkeypatch.setattr(deploy_mod, "_load_adapter",
                        lambda cr, an: _make_adapter_mod(calls))

    # Mock resolve_chat_binding to return the null binding — the contract: no
    # chat features → null binding. Don't rely on the real resolver's internals.
    null_binding = {"endpoint": None, "gate": None, "code": None, "feature_endpoints": {}}
    resolve_called = []

    def mock_resolve(grove, grove_env, env_name, corpus_root):
        resolve_called.append(True)
        return null_binding

    monkeypatch.setattr(deploy_mod, "resolve_chat_binding", mock_resolve)

    probe_called = []

    def fail_probe(*a, **kw):
        probe_called.append(True)

    monkeypatch.setattr(deploy_mod, "probe_chat", fail_probe)
    monkeypatch.setattr(deploy_mod, "resolve_credentials",
                        lambda remote, name, cr: {})

    deploy_mod.run(corpus, None, [str(content_dir), "prod"])

    # resolve_chat_binding was called (grove path), but returned null binding
    assert resolve_called, "resolve_chat_binding must be called for grove targets"
    # probe_chat must NOT be called when binding.endpoint is None
    assert not probe_called, "probe_chat must not be called when no chat features"
    build_call = next(c for c in calls if isinstance(c, tuple) and c[0] == "build")
    _, feature_endpoints, chat_config = build_call
    assert not feature_endpoints
    assert not chat_config


def test_probe_error_aborts_before_adapter(monkeypatch, tmp_path):
    """A ProbeError raised by probe_chat must abort the deploy before adapter.deploy."""
    from cli.infra.chat_probe import ProbeError

    calls = []
    corpus = _make_corpus(tmp_path)
    content_dir = corpus / "content" / "clients" / "acme" / "hub"

    monkeypatch.setattr(deploy_mod, "_resolve_spine", _fake_resolve_spine)
    monkeypatch.setattr(deploy_mod, "_load_shape_build",
                        lambda cr, sn: _make_build_mod(calls))
    monkeypatch.setattr(deploy_mod, "_load_adapter",
                        lambda cr, an: _make_adapter_mod(calls))
    monkeypatch.setattr(deploy_mod, "resolve_chat_binding",
                        lambda g, e, n, r: {
                            "endpoint": "https://ask.moui.co/api",
                            "gate": {"scheme": "access-code",
                                     "check": "https://ask.moui.co/api/check"},
                            "code": "BAD",
                            "feature_endpoints": {"assistant": "https://ask.moui.co"},
                        })
    monkeypatch.setattr(deploy_mod, "probe_chat",
                        lambda ep, origin, code, **kw: (_ for _ in ()).throw(
                            ProbeError("box rejected code (401)")))
    monkeypatch.setattr(deploy_mod, "resolve_credentials",
                        lambda remote, name, cr: {})

    with pytest.raises(ProbeError, match="401"):
        deploy_mod.run(corpus, None, [str(content_dir), "prod"])

    assert "adapter" not in calls, "adapter.deploy must not be called after ProbeError"
