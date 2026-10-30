from pathlib import Path

from cli.sync.encryption.base import EncryptionLayer


class NoneEncryptionLayer(EncryptionLayer):
    def encrypt_tree(self, folder: Path, extensions: list[str]) -> list[Path]:
        return []

    def decrypt_tree(self, folder: Path) -> list[Path]:
        return []
