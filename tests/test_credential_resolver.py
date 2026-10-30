"""Tests for credential resolution."""
import os
from pathlib import Path

import pytest
import yaml


def test_resolve_file_credential(tmp_path):
    from cli.infra.resolver import resolve_credentials

    secrets_path = tmp_path / "secrets" / "codeberg" / "client-x.yaml"
    secrets_path.parent.mkdir(parents=True)
    secrets_path.write_text(yaml.dump({"token": "ghp_xxxxx"}))

    remote = {
        "adapter": "codeberg_pages",
        "credential": "secrets/codeberg/client-x.yaml",
    }
    creds = resolve_credentials(remote, "codeberg/client-x", tmp_path)
    assert creds == {"token": "ghp_xxxxx"}


def test_resolve_ssh_agent():
    from cli.infra.resolver import resolve_credentials

    remote = {
        "adapter": "codeberg_pages",
        "credential": "ssh-agent",
    }
    creds = resolve_credentials(remote, "codeberg/moui-pages", Path("/dummy"))
    assert creds == {}


def test_resolve_env_credential(monkeypatch):
    from cli.infra.resolver import resolve_credentials

    monkeypatch.setenv("CODEBERG_TOKEN", "tok123")
    remote = {
        "adapter": "codeberg_pages",
        "credential": {"type": "env", "var": "CODEBERG_TOKEN"},
    }
    creds = resolve_credentials(remote, "codeberg/moui-pages", Path("/dummy"))
    assert creds == {"token": "tok123"}


def test_resolve_env_raises_when_unset():
    from cli.infra.resolver import resolve_credentials, CredentialError

    remote = {
        "adapter": "codeberg_pages",
        "credential": {"type": "env", "var": "NONEXISTENT_VAR_XYZ"},
    }
    with pytest.raises(CredentialError, match="NONEXISTENT_VAR_XYZ"):
        resolve_credentials(remote, "codeberg/x", Path("/dummy"))


def test_resolve_file_raises_when_missing(tmp_path):
    from cli.infra.resolver import resolve_credentials, CredentialError

    remote = {
        "adapter": "codeberg_pages",
        "credential": "secrets/codeberg/missing.yaml",
    }
    with pytest.raises(CredentialError, match="missing.yaml"):
        resolve_credentials(remote, "codeberg/missing", tmp_path)


def test_resolve_implicit_file_fallback(tmp_path):
    """When credential key is absent, try secrets/{provider}/{instance}.yaml."""
    from cli.infra.resolver import resolve_credentials

    secrets_path = tmp_path / "secrets" / "hetzner" / "moui.yaml"
    secrets_path.parent.mkdir(parents=True)
    secrets_path.write_text(yaml.dump({"ssh_key": "~/.ssh/id"}))

    remote = {"adapter": "hetzner"}  # no credential key
    creds = resolve_credentials(remote, "hetzner/moui", tmp_path)
    assert creds == {"ssh_key": "~/.ssh/id"}


def test_resolve_implicit_raises_with_tried_sources(tmp_path, monkeypatch):
    """When no credential key and no file exists, error lists what was tried."""
    from cli.infra.resolver import resolve_credentials, CredentialError

    monkeypatch.delenv("MOUI_HETZNER_MOUI_TOKEN", raising=False)
    remote = {"adapter": "hetzner"}  # no credential key
    with pytest.raises(CredentialError, match="Tried:"):
        resolve_credentials(remote, "hetzner/moui", tmp_path)
