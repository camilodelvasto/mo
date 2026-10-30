from __future__ import annotations

from pathlib import Path

from cli.sync.git_sync import (
    git_add_all,
    git_add_remote,
    git_commit,
    git_configure_user,
    git_init,
    git_pull,
    git_push,
    git_status,
)
from cli.sync.errors import GitCommandError, PushFailedError
from cli.sync.transport.base import PullOutcome, RepoStatus, SyncOutcome, Transport


class GitSyncAdapter(Transport):
    def __init__(self, remote_config: dict):
        self._remote_config = remote_config

    def initialize(self, folder: Path, remote_config: dict) -> None:
        git_init(folder)
        git_configure_user(
            folder,
            name=remote_config["git_user"],
            email=remote_config["git_email"],
        )
        git_add_remote(folder, name="origin", url=remote_config["repo"])

    def sync(self, folder: Path) -> SyncOutcome:
        from datetime import datetime, timezone
        git_add_all(folder)
        changed = self._changed_files(folder)
        message = self._remote_config["commit_message"].format(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            files=", ".join(changed) if changed else "no changes",
        )
        sha = git_commit(folder, message)
        pushed = False
        if sha is not None:
            try:
                git_push(folder, remote="origin", branch=self._remote_config["branch"])
                pushed = True
            except GitCommandError as exc:
                stderr = exc.stderr.lower() if exc.stderr else ""
                if "rejected" in stderr or "non-fast-forward" in stderr:
                    raise PushFailedError(f"push rejected: {exc.stderr.strip()}") from exc
                raise
        return SyncOutcome(
            committed_sha=sha,
            pushed=pushed,
        )

    def pull(self, folder: Path) -> PullOutcome:
        result = git_pull(folder, remote="origin", branch=self._remote_config["branch"])
        return PullOutcome(
            head=result.head,
            merged_commits=result.merged_commits,
            conflicts=[str(p) for p in result.conflicts],
        )

    @staticmethod
    def _changed_files(folder: Path) -> list[str]:
        """List staged file paths from git status --porcelain."""
        from cli.sync.git_sync import _run
        result = _run(["git", "status", "--porcelain"], cwd=folder)
        return [line[3:].strip() for line in result.stdout.splitlines() if line.strip()]

    def status(self, folder: Path) -> RepoStatus:
        result = git_status(folder)
        return RepoStatus(
            state=result.state,
            head=result.head,
            uncommitted=[str(p) for p in result.uncommitted],
            ahead=result.ahead,
            behind=result.behind,
            conflicts=[str(p) for p in result.conflicts],
        )
