from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from cli.sync.transport.base import PullOutcome, RepoStatus, SyncOutcome, Transport
from cli.sync.transport.encryption_wrapper import EncryptionWrapper


class FakeTransport(Transport):
    def __init__(self, *, sync_outcome: SyncOutcome, pull_outcome: PullOutcome, status_result: RepoStatus):
        self._sync_outcome = sync_outcome
        self._pull_outcome = pull_outcome
        self._status_result = status_result
        self.initialize_calls: list[tuple] = []
        self.sync_calls: list[Path] = []
        self.pull_calls: list[Path] = []
        self.status_calls: list[Path] = []

    def initialize(self, folder: Path, remote_config: dict) -> None:
        self.initialize_calls.append((folder, remote_config))

    def sync(self, folder: Path) -> SyncOutcome:
        self.sync_calls.append(folder)
        return self._sync_outcome

    def pull(self, folder: Path) -> PullOutcome:
        self.pull_calls.append(folder)
        return self._pull_outcome

    def status(self, folder: Path) -> RepoStatus:
        self.status_calls.append(folder)
        return self._status_result


@pytest.fixture
def canned():
    return dict(
        sync_outcome=SyncOutcome(committed_sha="abc123", pushed=True, files_changed=["a.txt"]),
        pull_outcome=PullOutcome(head="def456", merged_commits=["c1"], conflicts=[]),
        status_result=RepoStatus(state="clean", head="abc123"),
    )


@pytest.fixture
def fake(canned):
    return FakeTransport(**canned)


@pytest.fixture
def mock_layer():
    layer = MagicMock()
    layer.encrypt_tree.return_value = [Path("a.txt.age")]
    layer.decrypt_tree.return_value = [Path("a.txt")]
    return layer


@pytest.fixture
def wrapper(fake, mock_layer):
    return EncryptionWrapper(
        inner=fake,
        encryption_layer=mock_layer,
        extensions=[".txt", ".md"],
    )


class TestSync:
    def test_encrypt_tree_called_before_inner_sync(self, wrapper, fake, mock_layer):
        folder = Path("/test/folder")
        result = wrapper.sync(folder)

        mock_layer.encrypt_tree.assert_called_once_with(folder, [".txt", ".md"])
        assert fake.sync_calls == [folder]
        assert result.committed_sha == "abc123"
        assert result.pushed is True

    def test_encrypt_tree_order(self, wrapper, mock_layer):
        """encrypt_tree must be called before inner.sync; verify via call ordering."""
        call_order = []
        mock_layer.encrypt_tree.side_effect = lambda *a, **kw: call_order.append("encrypt")

        original_sync = wrapper._inner.sync

        def tracking_sync(folder):
            call_order.append("sync")
            return original_sync(folder)

        wrapper._inner.sync = tracking_sync
        wrapper.sync(Path("/test"))
        assert call_order == ["encrypt", "sync"]


class TestPull:
    def test_inner_pull_then_decrypt(self, wrapper, fake, mock_layer):
        folder = Path("/test/folder")
        result = wrapper.pull(folder)

        assert fake.pull_calls == [folder]
        mock_layer.decrypt_tree.assert_called_once_with(folder)
        assert result.head == "def456"

    def test_decrypt_order(self, wrapper, mock_layer):
        """inner.pull must be called before decrypt_tree."""
        call_order = []

        original_pull = wrapper._inner.pull

        def tracking_pull(folder):
            call_order.append("pull")
            return original_pull(folder)

        wrapper._inner.pull = tracking_pull
        mock_layer.decrypt_tree.side_effect = lambda *a, **kw: call_order.append("decrypt")

        wrapper.pull(Path("/test"))
        assert call_order == ["pull", "decrypt"]


class TestDelegation:
    def test_status_delegates_to_inner(self, wrapper, fake):
        folder = Path("/test/folder")
        result = wrapper.status(folder)

        assert fake.status_calls == [folder]
        assert result.state == "clean"

    def test_initialize_delegates_to_inner(self, wrapper, fake):
        folder = Path("/test/folder")
        cfg = {"url": "git@example.com:repo.git"}
        wrapper.initialize(folder, cfg)

        assert fake.initialize_calls == [(folder, cfg)]
