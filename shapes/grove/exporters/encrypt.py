"""Grove encryption — AES-256-GCM envelope from HTML content."""
import base64
import json
import os
from typing import Callable


def generate_mnemonic() -> str:
    """Generate a new BIP-39 mnemonic (128-bit, 12 words)."""
    from mnemonic import Mnemonic
    return Mnemonic("english").generate(strength=128)


def make_encryptor(mnemonic: str) -> Callable[[str, dict], str]:
    """Return a closure that encrypts HTML into an envelope JSON string.

    The closure receives (html_content, post_meta) and returns the envelope
    as a JSON string. post_meta provides the plaintext meta field.
    The mnemonic is closed over — it never appears in the caller's scope.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    def _encrypt(html: str, meta: dict) -> str:
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32,
            salt=salt, iterations=100000,
        )
        key = kdf.derive(mnemonic.encode())
        iv = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(iv, html.encode(), None)

        envelope = {
            "encrypted": True,
            "key_id": None,
            "meta": {"title": meta["title"]},
            "salt": base64.b64encode(salt).decode(),
            "iv": base64.b64encode(iv).decode(),
            "payload": base64.b64encode(ciphertext).decode(),
        }
        return json.dumps(envelope, ensure_ascii=False)

    return _encrypt


def make_asset_encryptor(mnemonic: str) -> tuple[Callable[[bytes], str], str]:
    """Return (encryptor_fn, salt_b64) for batch asset encryption.

    All files encrypted with the same salt — one PBKDF2 derivation at build,
    one at runtime. Each file gets a unique IV. The shared salt is stored in
    the bundle so the SW can derive the key once and cache it.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    salt = os.urandom(16)
    salt_b64 = base64.b64encode(salt).decode()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32,
        salt=salt, iterations=100000,
    )
    key = kdf.derive(mnemonic.encode())
    aesgcm = AESGCM(key)

    def _encrypt(data: bytes) -> str:
        iv = os.urandom(12)
        ciphertext = aesgcm.encrypt(iv, data, None)
        envelope = {
            "encrypted": True,
            "salt": salt_b64,
            "iv": base64.b64encode(iv).decode(),
            "payload": base64.b64encode(ciphertext).decode(),
        }
        return json.dumps(envelope, ensure_ascii=False)

    return _encrypt, salt_b64
