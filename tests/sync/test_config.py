import pytest
from pathlib import Path

from cli.sync.config import (
    SyncDeclaration,
    EncryptionConfig,
    SyncSettings,
    DeviceState,
    load_sync_declaration,
)
from cli.sync.errors import ConfigValidationError, UnsupportedVersionError


def test_sync_declaration_minimal(tmp_path):
    """Minimal valid declaration: version, target, remote, encryption.type=none."""
    yaml_content = """\
version: 1
target: ../../content/moui
remote: codeberg/moui-content-sync
encryption:
  type: none
"""
    f = tmp_path / "moui.yaml"
    f.write_text(yaml_content)
    decl = load_sync_declaration(f)
    assert decl.version == 1
    assert decl.target == "../../content/moui"
    assert decl.remote == "codeberg/moui-content-sync"
    assert decl.encryption.type == "none"
    assert decl.sync is None


def test_sync_declaration_with_age_ssh(tmp_path):
    yaml_content = """\
version: 1
target: ..
remote: github/moui-infra-sync
encryption:
  type: age-ssh
  recipients:
    - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest1 laptop"
    - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest2 work"
sync:
  debounce_seconds: 30
  max_debounce_seconds: 300
"""
    f = tmp_path / "self.yaml"
    f.write_text(yaml_content)
    decl = load_sync_declaration(f)
    assert decl.encryption.type == "age-ssh"
    assert len(decl.encryption.recipients) == 2
    assert decl.sync.debounce_seconds == 30
    assert decl.sync.max_debounce_seconds == 300


def test_sync_declaration_age_ssh_requires_recipients(tmp_path):
    yaml_content = """\
version: 1
target: ../content
remote: codeberg/sync
encryption:
  type: age-ssh
"""
    f = tmp_path / "bad.yaml"
    f.write_text(yaml_content)
    with pytest.raises(ConfigValidationError):
        load_sync_declaration(f)


def test_sync_declaration_missing_required_field(tmp_path):
    yaml_content = """\
version: 1
target: ../content
encryption:
  type: none
"""
    f = tmp_path / "bad.yaml"
    f.write_text(yaml_content)
    with pytest.raises(ConfigValidationError):
        load_sync_declaration(f)


def test_sync_declaration_extra_field_rejected(tmp_path):
    yaml_content = """\
version: 1
target: ../content
remote: codeberg/sync
encryption:
  type: none
bogus: true
"""
    f = tmp_path / "bad.yaml"
    f.write_text(yaml_content)
    with pytest.raises(ConfigValidationError):
        load_sync_declaration(f)


def test_sync_declaration_wrong_version(tmp_path):
    yaml_content = """\
version: 99
target: ../content
remote: codeberg/sync
encryption:
  type: none
"""
    f = tmp_path / "bad.yaml"
    f.write_text(yaml_content)
    with pytest.raises(UnsupportedVersionError):
        load_sync_declaration(f)


def test_device_state_defaults():
    state = DeviceState()
    assert state.version == 1
    assert state.device.id is not None
    assert state.device.display_name is not None
    assert state.overrides == {}
