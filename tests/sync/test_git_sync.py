import subprocess
from pathlib import Path

import pytest

from cli.sync.git_sync import (
    PullResult,
    StatusResult,
    git_add_all,
    git_add_remote,
    git_clone,
    git_commit,
    git_configure_user,
    git_init,
    git_pull,
    git_push,
    git_status,
)
from cli.sync.errors import GitCommandError


def _shell(args, cwd, **kwargs):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True, **kwargs)


def _make_clone(bare_repo: Path, tmp_path_factory, name: str = "clone") -> Path:
    dest = tmp_path_factory.mktemp(name)
    subprocess.run(
        ["git", "clone", str(bare_repo), str(dest)],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=str(dest), capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(dest), capture_output=True, text=True, check=True,
    )
    return dest


class TestGitInit:
    def test_creates_git_dir(self, tmp_path):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        assert (folder / ".git").exists()

    def test_idempotent(self, tmp_path):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        git_init(folder)  # should not raise
        assert (folder / ".git").exists()


class TestGitConfigureUser:
    def test_sets_name_and_email(self, tmp_path):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        git_configure_user(folder, "Alice", "alice@example.com")

        name = _shell(["git", "config", "user.name"], cwd=folder).stdout.strip()
        email = _shell(["git", "config", "user.email"], cwd=folder).stdout.strip()
        assert name == "Alice"
        assert email == "alice@example.com"


class TestGitAddRemote:
    def test_adds_remote(self, tmp_path, bare_repo):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        git_add_remote(folder, "origin", str(bare_repo))

        result = _shell(["git", "remote", "-v"], cwd=folder)
        assert str(bare_repo) in result.stdout

    def test_idempotent_same_url(self, tmp_path, bare_repo):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        git_add_remote(folder, "origin", str(bare_repo))
        git_add_remote(folder, "origin", str(bare_repo))  # no-op

        lines = [l for l in _shell(["git", "remote", "-v"], cwd=folder).stdout.strip().splitlines() if l]
        # Should have exactly 2 lines (fetch + push), not duplicates
        assert len(lines) == 2

    def test_updates_url_if_different(self, tmp_path, bare_repo, tmp_path_factory):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        git_add_remote(folder, "origin", str(bare_repo))

        new_bare = tmp_path_factory.mktemp("bare2") / "other.git"
        subprocess.run(["git", "init", "--bare", str(new_bare)], check=True, capture_output=True)
        git_add_remote(folder, "origin", str(new_bare))

        result = _shell(["git", "remote", "get-url", "origin"], cwd=folder)
        assert result.stdout.strip() == str(new_bare)


class TestGitCommitAndPush:
    def test_commit_returns_sha(self, tmp_path, bare_repo):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        git_configure_user(folder, "Test", "test@test.com")
        git_add_remote(folder, "origin", str(bare_repo))

        (folder / "file.txt").write_text("hello")
        git_add_all(folder)
        sha = git_commit(folder, "initial commit")

        assert sha is not None
        assert len(sha) == 40

    def test_commit_returns_none_when_clean(self, tmp_path):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        git_configure_user(folder, "Test", "test@test.com")

        (folder / "file.txt").write_text("hello")
        git_add_all(folder)
        git_commit(folder, "initial")

        result = git_commit(folder, "should be none")
        assert result is None

    def test_push_to_bare(self, tmp_path, bare_repo):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        git_configure_user(folder, "Test", "test@test.com")
        git_add_remote(folder, "origin", str(bare_repo))

        (folder / "file.txt").write_text("hello")
        git_add_all(folder)
        git_commit(folder, "initial commit")
        git_push(folder, "origin", "main")

        # Verify commit arrived in bare repo
        log = _shell(["git", "log", "--oneline"], cwd=bare_repo)
        assert "initial commit" in log.stdout


class TestGitPull:
    def test_pull_receives_changes(self, bare_repo, tmp_path_factory):
        clone_a = _make_clone(bare_repo, tmp_path_factory, "clone_a")
        # Need an initial commit so main branch exists
        (clone_a / "seed.txt").write_text("seed")
        _shell(["git", "add", "-A"], cwd=clone_a)
        _shell(["git", "commit", "-m", "seed"], cwd=clone_a)
        _shell(["git", "push", "-u", "origin", "main"], cwd=clone_a)

        clone_b = _make_clone(bare_repo, tmp_path_factory, "clone_b")

        # Push from clone_a
        (clone_a / "new.txt").write_text("content")
        _shell(["git", "add", "-A"], cwd=clone_a)
        _shell(["git", "commit", "-m", "add new file"], cwd=clone_a)
        _shell(["git", "push"], cwd=clone_a)

        # Pull into clone_b
        result = git_pull(clone_b, "origin", "main")

        assert isinstance(result, PullResult)
        assert len(result.head) == 40
        assert (clone_b / "new.txt").read_text() == "content"
        assert len(result.merged_commits) > 0


class TestGitStatus:
    def test_not_initialized(self, tmp_path):
        folder = tmp_path / "plain"
        folder.mkdir()
        result = git_status(folder)
        assert result.state == "not_initialized"

    def test_clean(self, tmp_path):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        git_configure_user(folder, "Test", "test@test.com")
        (folder / "file.txt").write_text("hello")
        git_add_all(folder)
        git_commit(folder, "init")

        result = git_status(folder)
        assert result.state == "clean"
        assert result.head is not None
        assert len(result.uncommitted) == 0

    def test_dirty(self, tmp_path):
        folder = tmp_path / "repo"
        folder.mkdir()
        git_init(folder)
        git_configure_user(folder, "Test", "test@test.com")
        (folder / "file.txt").write_text("hello")
        git_add_all(folder)
        git_commit(folder, "init")

        (folder / "file.txt").write_text("changed")
        result = git_status(folder)
        assert result.state == "dirty"
        assert len(result.uncommitted) > 0


class TestGitClone:
    def test_clones_repo(self, bare_repo, tmp_path_factory):
        # Seed the bare repo with a commit
        staging = tmp_path_factory.mktemp("staging")
        subprocess.run(["git", "clone", str(bare_repo), str(staging)], capture_output=True, text=True, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=str(staging), capture_output=True, text=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(staging), capture_output=True, text=True, check=True)
        (staging / "readme.txt").write_text("hi")
        _shell(["git", "add", "-A"], cwd=staging)
        _shell(["git", "commit", "-m", "seed"], cwd=staging)
        _shell(["git", "push", "-u", "origin", "main"], cwd=staging)

        dest = tmp_path_factory.mktemp("dest") / "cloned"
        git_clone(str(bare_repo), dest)

        assert (dest / ".git").exists()
        assert (dest / "readme.txt").read_text() == "hi"
