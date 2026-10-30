from abc import ABC, abstractmethod
from pathlib import Path


class EncryptionLayer(ABC):
    @abstractmethod
    def encrypt_tree(self, folder: Path, extensions: list[str]) -> list[Path]:
        """Encrypt plaintext files matching extensions, return list of .age paths created."""
        ...

    @abstractmethod
    def decrypt_tree(self, folder: Path) -> list[Path]:
        """Decrypt .age files using SSH agent, return list of decrypted plaintext paths."""
        ...
