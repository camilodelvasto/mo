from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class SyncOutcome(BaseModel):
    committed_sha: str | None
    pushed: bool
    files_changed: list[str] = []


class PullOutcome(BaseModel):
    head: str
    merged_commits: list[str] = []
    conflicts: list[str] = []  # Reconciler seam (v1)


class RepoStatus(BaseModel):
    state: Literal[
        "clean", "dirty", "ahead", "behind", "diverged", "conflicted", "not_initialized"
    ]
    head: str | None = None
    uncommitted: list[str] = []
    ahead: int = 0
    behind: int = 0
    conflicts: list[str] = []


class Transport(ABC):
    @abstractmethod
    def initialize(self, folder: Path, remote_config: dict) -> None: ...

    @abstractmethod
    def sync(self, folder: Path) -> SyncOutcome: ...

    @abstractmethod
    def pull(self, folder: Path) -> PullOutcome: ...

    @abstractmethod
    def status(self, folder: Path) -> RepoStatus: ...
