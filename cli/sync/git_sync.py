from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from cli.sync.errors import GitCommandError


@dataclass
class PullResult:
    head: str
    merged_commits: list[str] = field(default_factory=list)
    conflicts: list[Path] = field(default_factory=list)


@dataclass
class StatusResult:
    state: str  # clean, dirty, ahead, behind, diverged, conflicted, not_initialized
    head: str | None = None
    uncommitted: list[Path] = field(default_factory=list)
    ahead: int = 0
    behind: int = 0
    conflicts: list[Path] = field(default_factory=list)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=_env(),
    )
    if check and result.returncode != 0:
        raise GitCommandError(
            cmd=args,
            returncode=result.returncode,
            stderr=result.stderr,
        )
    return result


def git_init(folder: Path) -> None:
    if (folder / ".git").exists():
        return
    _run(["git", "init"], cwd=folder)


def git_configure_user(folder: Path, name: str, email: str) -> None:
    _run(["git", "config", "user.name", name], cwd=folder)
    _run(["git", "config", "user.email", email], cwd=folder)


def git_add_remote(folder: Path, name: str, url: str) -> None:
    result = _run(["git", "remote", "get-url", name], cwd=folder, check=False)
    if result.returncode == 0:
        current_url = result.stdout.strip()
        if current_url == url:
            return
        _run(["git", "remote", "set-url", name, url], cwd=folder)
    else:
        _run(["git", "remote", "add", name, url], cwd=folder)


def git_add_all(folder: Path) -> None:
    _run(["git", "add", "-A"], cwd=folder)


def git_commit(folder: Path, message: str) -> str | None:
    status = _run(["git", "status", "--porcelain"], cwd=folder)
    if not status.stdout.strip():
        return None
    _run(["git", "commit", "-m", message], cwd=folder)
    sha = _run(["git", "rev-parse", "HEAD"], cwd=folder)
    return sha.stdout.strip()


def git_push(folder: Path, remote: str, branch: str) -> None:
    _run(["git", "push", "-u", remote, branch], cwd=folder)


def git_pull(folder: Path, remote: str, branch: str) -> PullResult:
    before = _run(["git", "rev-parse", "HEAD"], cwd=folder, check=False)
    before_sha = before.stdout.strip() if before.returncode == 0 else None

    _run(["git", "pull", remote, branch], cwd=folder)

    after = _run(["git", "rev-parse", "HEAD"], cwd=folder)
    after_sha = after.stdout.strip()

    merged_commits: list[str] = []
    if before_sha and before_sha != after_sha:
        log = _run(
            ["git", "log", "--oneline", f"{before_sha}..{after_sha}"],
            cwd=folder,
        )
        merged_commits = [
            line.strip() for line in log.stdout.strip().splitlines() if line.strip()
        ]

    conflicts_result = _run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=folder,
        check=False,
    )
    conflicts = [
        Path(f) for f in conflicts_result.stdout.strip().splitlines() if f.strip()
    ]

    return PullResult(
        head=after_sha,
        merged_commits=merged_commits,
        conflicts=conflicts,
    )


def git_clone(url: str, dest: Path) -> None:
    _run(["git", "clone", url, str(dest)], cwd=dest.parent)


def git_status(folder: Path) -> StatusResult:
    if not (folder / ".git").exists():
        return StatusResult(state="not_initialized")

    head_result = _run(["git", "rev-parse", "HEAD"], cwd=folder, check=False)
    head = head_result.stdout.strip() if head_result.returncode == 0 else None

    porcelain = _run(["git", "status", "--porcelain"], cwd=folder)
    uncommitted: list[Path] = []
    conflicts: list[Path] = []
    for line in porcelain.stdout.splitlines():
        if not line.strip():
            continue
        status_code = line[:2]
        filepath = Path(line[3:].strip())
        if "U" in status_code:
            conflicts.append(filepath)
        else:
            uncommitted.append(filepath)

    if conflicts:
        return StatusResult(
            state="conflicted",
            head=head,
            uncommitted=uncommitted,
            conflicts=conflicts,
        )

    lr = _run(
        ["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
        cwd=folder,
        check=False,
    )
    ahead = 0
    behind = 0
    if lr.returncode == 0:
        parts = lr.stdout.strip().split()
        if len(parts) == 2:
            ahead = int(parts[0])
            behind = int(parts[1])

    if ahead > 0 and behind > 0:
        state = "diverged"
    elif ahead > 0:
        state = "ahead"
    elif behind > 0:
        state = "behind"
    elif uncommitted:
        state = "dirty"
    else:
        state = "clean"

    return StatusResult(
        state=state,
        head=head,
        uncommitted=uncommitted,
        ahead=ahead,
        behind=behind,
        conflicts=conflicts,
    )
