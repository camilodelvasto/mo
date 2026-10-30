from pathlib import Path

from cli.sync.encryption.base import EncryptionLayer
from cli.sync.transport.base import PullOutcome, RepoStatus, SyncOutcome, Transport


class EncryptionWrapper(Transport):
    def __init__(
        self,
        *,
        inner: Transport,
        encryption_layer: EncryptionLayer,
        extensions: list[str],
    ):
        self._inner = inner
        self._encryption_layer = encryption_layer
        self._extensions = extensions

    def initialize(self, folder: Path, remote_config: dict) -> None:
        self._inner.initialize(folder, remote_config)

    def sync(self, folder: Path) -> SyncOutcome:
        self._encryption_layer.encrypt_tree(folder, self._extensions)
        return self._inner.sync(folder)

    def pull(self, folder: Path) -> PullOutcome:
        result = self._inner.pull(folder)
        self._encryption_layer.decrypt_tree(folder)
        return result

    def status(self, folder: Path) -> RepoStatus:
        return self._inner.status(folder)
