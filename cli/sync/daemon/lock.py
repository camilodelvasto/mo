import fcntl
import os
from pathlib import Path

from cli.sync.errors import WorkspaceLockedError


def acquire_lock(pid_path: Path) -> int:
    fd = os.open(str(pid_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        existing_pid = os.read(fd, 64).decode().strip()
        os.close(fd)
        raise WorkspaceLockedError(
            f"workspace locked by PID {existing_pid}"
        )
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode())
    os.fsync(fd)
    return fd


def release_lock(fd: int, pid_path: Path) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        pid_path.unlink()
    except (OSError, FileNotFoundError):
        pass
