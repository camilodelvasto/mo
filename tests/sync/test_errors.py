from cli.sync.errors import (
    MouiSyncError,
    ConfigValidationError,
    UnsupportedVersionError,
    RemoteNotFoundError,
    TargetMissingError,
    InfrastructureNotFoundError,
    UnknownAdapterError,
    InfrastructureFolderUnavailableError,
    WorkspaceLockedError,
    FolderNotTrackedError,
    SSHAccessError,
    GitCommandError,
    PushFailedError,
    PullFailedError,
    RepoDivergedError,
    EncryptionError,
    DecryptionError,
    InvalidRecipientError,
    SSHAgentUnavailableError,
    UnknownMethodError,
    ProtocolVersionMismatchError,
)
import pytest


ALL_ERRORS = [
    ConfigValidationError,
    UnsupportedVersionError,
    RemoteNotFoundError,
    TargetMissingError,
    InfrastructureNotFoundError,
    UnknownAdapterError,
    InfrastructureFolderUnavailableError,
    WorkspaceLockedError,
    FolderNotTrackedError,
    SSHAccessError,
    GitCommandError,
    PushFailedError,
    PullFailedError,
    RepoDivergedError,
    EncryptionError,
    DecryptionError,
    InvalidRecipientError,
    SSHAgentUnavailableError,
    UnknownMethodError,
    ProtocolVersionMismatchError,
]


def test_base_inherits_from_exception():
    assert issubclass(MouiSyncError, Exception)


@pytest.mark.parametrize("cls", ALL_ERRORS)
def test_all_errors_inherit_from_moui_sync_error(cls):
    assert issubclass(cls, MouiSyncError)


def test_errors_carry_messages():
    err = ConfigValidationError("bad config")
    assert str(err) == "bad config"


def test_git_command_error_attributes():
    err = GitCommandError(cmd="git push", returncode=128, stderr="fatal: no remote")
    assert err.cmd == "git push"
    assert err.returncode == 128
    assert err.stderr == "fatal: no remote"
    assert isinstance(err, MouiSyncError)


def test_target_missing_error():
    err = TargetMissingError("/path/to/folder")
    assert isinstance(err, MouiSyncError)
    assert "/path/to/folder" in str(err)


def test_infrastructure_not_found_error():
    err = InfrastructureNotFoundError("/some/path")
    assert isinstance(err, MouiSyncError)
    assert "/some/path" in str(err)
