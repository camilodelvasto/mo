# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
import yaml
from pathlib import Path
from cli.commands import serve

def _grove(tmp_path, with_chat=True):
    g = {"id": "t", "title": "T", "features": []}
    if with_chat:
        g["features"] = [{"type": "chat", "id": "ghost", "ask": "write"}]
    (tmp_path / "grove.yaml").write_text(yaml.safe_dump(g))
    return tmp_path

def test_chat_endpoint_short_circuits_to_open_chat(tmp_path):
    root = _grove(tmp_path)
    cfg = serve.resolve_dev_chat_config(tmp_path, root, "local", "http://127.0.0.1:8787/api")
    assert cfg == {"endpoint": "http://127.0.0.1:8787/api", "gate": None}

def test_no_chat_feature_returns_none(tmp_path):
    root = _grove(tmp_path, with_chat=False)
    assert serve.resolve_dev_chat_config(tmp_path, root, "local", None) is None

def test_env_resolves_binding_without_secret(tmp_path, monkeypatch):
    root = _grove(tmp_path)
    from cli.infra import services
    monkeypatch.setattr(serve, "load_target", lambda cp, r: {
        "environments": {"local": {"services": {"chat": "corpus-server/moui"}}}})
    monkeypatch.setattr(services, "load_target", lambda ref, r: {
        "stack": "corpus-server",
        "environments": {"local": {"domain": "api.local.test", "auth": {"scheme": "access-code"}}}})
    cfg = serve.resolve_dev_chat_config(tmp_path, root, "local", None)
    assert cfg["endpoint"] == "https://api.local.test/api"
    assert cfg["gate"] == {"scheme": "access-code", "check": "https://api.local.test/api/check"}

def test_chat_endpoint_and_env_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit):
        serve.run(tmp_path, "grove",
                  ["somepath", "--chat-endpoint", "http://127.0.0.1:8787/api",
                   "--env", "local"])
