from __future__ import annotations

import os
from pathlib import Path

import pyrage
import pyrage.ssh

from cli.sync.encryption.base import EncryptionLayer
from cli.sync.errors import (
    DecryptionError,
    EncryptionError,
    InvalidRecipientError,
    SSHAgentUnavailableError,
)


class AgeSSHEncryptionLayer(EncryptionLayer):
    def __init__(self, recipients: list[str]):
        self._recipients: list[pyrage.ssh.Recipient] = []
        for r in recipients:
            try:
                self._recipients.append(pyrage.ssh.Recipient.from_str(r))
            except Exception as exc:
                raise InvalidRecipientError(
                    f"failed to parse recipient: {r}"
                ) from exc

    def encrypt_tree(self, folder: Path, extensions: list[str]) -> list[Path]:
        created: list[Path] = []
        for ext in extensions:
            pattern = f"**/*{ext}"
            for plain_path in sorted(folder.glob(pattern)):
                if not plain_path.is_file():
                    continue
                if plain_path.suffix == ".age":
                    continue
                age_path = plain_path.with_name(plain_path.name + ".age")
                try:
                    plaintext = plain_path.read_bytes()
                    ciphertext = pyrage.encrypt(plaintext, self._recipients)
                    age_path.write_bytes(ciphertext)
                    created.append(age_path)
                except Exception as exc:
                    raise EncryptionError(
                        f"failed to encrypt {plain_path}"
                    ) from exc
        return created

    def decrypt_tree(self, folder: Path) -> list[Path]:
        sock = os.environ.get("SSH_AUTH_SOCK")
        if not sock:
            raise SSHAgentUnavailableError(
                "SSH_AUTH_SOCK not set; cannot decrypt without SSH agent"
            )
        # Delegate to shared implementation with agent-based identity
        # pyrage.ssh.Identity requires a key string; agent forwarding
        # is not directly supported by pyrage — callers needing agent
        # support should use decrypt_tree_with_key with their loaded key.
        raise SSHAgentUnavailableError(
            "direct SSH agent decryption not yet implemented; "
            "use decrypt_tree_with_key with an explicit private key"
        )

    def decrypt_tree_with_key(
        self, folder: Path, private_key_pem: bytes
    ) -> list[Path]:
        try:
            identity = pyrage.ssh.Identity.from_buffer(private_key_pem)
        except Exception as exc:
            raise DecryptionError("failed to parse private key") from exc

        decrypted: list[Path] = []

        # Decrypt every .age file
        for age_path in sorted(folder.rglob("*.age")):
            if not age_path.is_file():
                continue
            plain_path = age_path.with_name(age_path.name.removesuffix(".age"))
            try:
                ciphertext = age_path.read_bytes()
                plaintext = pyrage.decrypt(ciphertext, [identity])
                plain_path.write_bytes(plaintext)
                decrypted.append(plain_path)
            except Exception as exc:
                raise DecryptionError(
                    f"failed to decrypt {age_path}"
                ) from exc

        # Orphan cleanup: remove plaintext files whose .age counterpart is gone
        for plain_path in sorted(folder.rglob("*")):
            if not plain_path.is_file():
                continue
            if plain_path.suffix == ".age":
                continue
            age_counterpart = plain_path.with_name(plain_path.name + ".age")
            if not age_counterpart.exists():
                plain_path.unlink()

        return decrypted
