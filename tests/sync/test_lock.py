import os
from cli.sync.daemon.lock import acquire_lock, release_lock
from cli.sync.errors import WorkspaceLockedError
import pytest


def test_acquire_and_release(tmp_path):
    pid_path = tmp_path / "sync.pid"
    fd = acquire_lock(pid_path)
    assert pid_path.exists()
    content = pid_path.read_text()
    assert content.strip() == str(os.getpid())
    release_lock(fd, pid_path)
    assert not pid_path.exists()


def test_double_acquire_raises(tmp_path):
    pid_path = tmp_path / "sync.pid"
    fd = acquire_lock(pid_path)
    try:
        with pytest.raises(WorkspaceLockedError):
            acquire_lock(pid_path)
    finally:
        release_lock(fd, pid_path)
