# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
import yaml
from pathlib import Path

from cli.commands.deploy import _resolve_service_worker

ROOT = Path(__file__).resolve().parent.parent


def test_remote_baseline_used_when_env_omits():
    assert _resolve_service_worker({}, {"service_worker": True}, "gh/x") is True
    assert _resolve_service_worker({}, {"service_worker": False}, "gh/x") is False


def test_env_overrides_remote():
    # staging turns the SW off even though the remote's baseline is on
    assert _resolve_service_worker(
        {"service_worker": False}, {"service_worker": True}, "gh/x") is False
    assert _resolve_service_worker(
        {"service_worker": True}, {"service_worker": False}, "gh/x") is True


def test_remote_missing_declaration_fails_loud():
    with pytest.raises(SystemExit, match="cb/x"):
        _resolve_service_worker({}, {"adapter": "codeberg_pages"}, "cb/x")


def test_grove_hosting_remotes_declare_service_worker():
    if not (ROOT / "infrastructure/remotes.yaml").is_file():
        pytest.skip("remotes.yaml not present (gitignored, present only on a working checkout)")
    remotes = yaml.safe_load((ROOT / "infrastructure/remotes.yaml").read_text())["remotes"]
    for rid in ("github/moui-grove", "codeberg/moui-pages"):
        assert "service_worker" in remotes[rid], \
            f"grove-hosting remote {rid} must declare service_worker"
