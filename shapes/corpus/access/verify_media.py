# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Verify + compress + sign one uploaded image. The declared ask policy is the
authority (accept/max_bytes); verification/compression is the swappable media.image
capability; the box then HMAC-signs the canonical bytes so resends are trusted by a
signature check. Every rejection is a named AttachmentError — no silent pass."""
import base64
import hashlib
import subprocess
from pathlib import Path

from shapes.corpus.access import attest
from shapes.corpus.access.errors import AttachmentError
from shapes.corpus.engine import capabilities
from shapes.corpus.engine.errors import CapabilityError

CANONICAL_MEDIA_TYPE = "image/webp"   # media.image always emits WebP; the signed type


def _kind_of(media_type: str) -> str:
    """The accept vocabulary is a coarse kind ('image'), not a MIME type."""
    return media_type.split("/", 1)[0]


def media_binding(machine_root: Path) -> dict:
    """The media.image binding, validated. A misbound capability is the BOX's fault,
    never the image's: a CapabilityError (500 naming the binding), not a rejection the
    user would read as "bad image". The bounds are values, not just keys."""
    binding = capabilities.resolve("media.image", capabilities.load_table(machine_root))
    if binding.get("reads") != "stdin":
        raise CapabilityError(
            f"media.image must declare reads: stdin (got {binding.get('reads')!r})")
    if "timeout" not in binding:
        raise CapabilityError("media.image declares no timeout; the box never runs an unbounded decode")
    timeout = binding["timeout"]
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise CapabilityError(
            f"media.image timeout must be a positive number of seconds (got {timeout!r})")
    if "concurrency" not in binding:
        raise CapabilityError(
            "media.image declares no concurrency; the box never runs unmetered decodes")
    concurrency = binding["concurrency"]
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
        raise CapabilityError(
            f"media.image concurrency must be an integer >= 1 (got {concurrency!r})")
    return binding


def verify_and_sign(machine_root: Path, ask_id: str, policy: dict, raw: bytes,
                    declared_type: str) -> dict:
    # The schema requires only `accept`; max_bytes is an optional declared bound.
    if "max_bytes" in policy and len(raw) > policy["max_bytes"]:
        raise AttachmentError("too_large",
            f"attachment is {len(raw)} bytes; the ask allows at most {policy['max_bytes']}")
    if _kind_of(declared_type) not in policy["accept"]:
        raise AttachmentError("wrong_type",
            f"attachment type {declared_type!r} is not in accept={policy['accept']}")

    binding = media_binding(machine_root)
    # The secret is loaded BEFORE the decode: a box that cannot sign refuses at once,
    # not after up to `timeout` seconds of work it would throw away.
    secret = attest.load_secret(machine_root)
    try:
        proc = subprocess.run(binding["run"], input=raw, capture_output=True,
                              timeout=binding["timeout"])
    except subprocess.TimeoutExpired:
        raise AttachmentError("undecodable",
            f"media.image did not finish within its declared {binding['timeout']}s")
    if proc.returncode != 0 or not proc.stdout:
        raise AttachmentError("undecodable",
            proc.stderr.decode(errors="replace").strip() or "media.image rejected the input")
    canonical = proc.stdout

    sha = hashlib.sha256(canonical).hexdigest()
    signature = attest.sign(secret, ask_id, sha, CANONICAL_MEDIA_TYPE)
    return {"data": base64.b64encode(canonical).decode(),
            "signature": signature,
            "media_type": CANONICAL_MEDIA_TYPE,
            "bytes": len(canonical)}
