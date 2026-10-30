from unittest.mock import patch

import pytest
from cli.sync.config import SyncDeclaration, EncryptionConfig
from cli.sync.errors import UnknownAdapterError
from cli.sync.transport.build import build_transport


def _make_declaration(enc_type="none", recipients=None):
    return SyncDeclaration(
        version=1,
        target="../content",
        remote="test/remote",
        encryption=EncryptionConfig(
            type=enc_type,
            recipients=recipients or [],
        ),
    )


def test_build_transport_git_sync_no_encryption():
    decl = _make_declaration()
    remote = {"adapter": "git_sync", "repo": "git@host:r.git", "branch": "main",
              "git_user": "U", "git_email": "e@x.com", "credential": "ssh-agent"}
    t = build_transport(decl, remote)
    from shapes.shared.adapters.git_sync import GitSyncAdapter
    assert isinstance(t, GitSyncAdapter)


def test_build_transport_unknown_adapter():
    decl = _make_declaration()
    remote = {"adapter": "s3_bucket"}
    with pytest.raises(UnknownAdapterError):
        build_transport(decl, remote)


@patch("cli.sync.transport.build.AgeSSHEncryptionLayer")
def test_build_transport_age_ssh(mock_age_cls):
    decl = _make_declaration(
        enc_type="age-ssh",
        recipients=["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest key"],
    )
    remote = {"adapter": "git_sync", "repo": "git@host:r.git", "branch": "main",
              "git_user": "U", "git_email": "e@x.com", "credential": "ssh-agent"}
    t = build_transport(decl, remote)
    from cli.sync.transport.encryption_wrapper import EncryptionWrapper
    assert isinstance(t, EncryptionWrapper)
