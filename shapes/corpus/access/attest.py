# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The box-issued cleanliness token. The box HMAC-signs {ask, sha256, media_type} of
a canonical image it has verified under that ask's policy; on every resend to that
ask it recomputes the hash and checks the HMAC — trusting its own prior verdict
without re-decoding. A token issued under one ask never verifies on another. Only
the box signs AND verifies, so the honest primitive is symmetric HMAC (not Ed25519).
The contract is 'a box-issued signed cleanliness token'; swap to a keypair the day
verification moves off-box. No fallback: a missing secret or a bad signature throws."""
import hashlib
import hmac
import json
import re
from pathlib import Path


class AttestError(Exception):
    """The secret is absent, or an attachment's signature is malformed or does not
    match its ask/bytes/media_type."""


_SIGNATURE = re.compile(r"[0-9a-f]{64}")


def load_secret(machine_root: Path) -> bytes:
    path = machine_root / "attest.secret"
    if not path.is_file():
        raise AttestError(
            f"no attest secret at {path} — the box signs attachments with it; "
            "write a random secret there (gitignored) before serving attachments")
    secret = path.read_text().strip().encode()
    if not secret:
        raise AttestError(f"attest secret at {path} is empty")
    return secret


def _message(ask_id: str, sha256_hex: str, media_type: str) -> bytes:
    """The signed claim: THIS ask verified THESE bytes as THIS type. A JSON array, so
    no field's content can shift into another's."""
    return json.dumps([ask_id, sha256_hex, media_type]).encode()


def sign(secret: bytes, ask_id: str, sha256_hex: str, media_type: str) -> str:
    return hmac.new(secret, _message(ask_id, sha256_hex, media_type), hashlib.sha256).hexdigest()


def verify(secret: bytes, ask_id: str, data: bytes, media_type: str, signature) -> None:
    if not isinstance(signature, str) or not _SIGNATURE.fullmatch(signature):
        raise AttestError("attachment signature is not a 64-hex HMAC")
    expected = sign(secret, ask_id, hashlib.sha256(data).hexdigest(), media_type)
    if not hmac.compare_digest(expected, signature):
        raise AttestError("attachment signature does not match its ask/bytes/media_type")
