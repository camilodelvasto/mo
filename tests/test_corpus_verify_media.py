# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import base64
import hashlib
import io
import json
import sys

import pytest
from PIL import Image

from shapes.corpus.access import verify_media, attest
from shapes.corpus.access.errors import AttachmentError

POLICY = {"accept": ["image"], "max_count": 3, "max_bytes": 10_000_000}

def _jpeg(nbytes_hint=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", nbytes_hint, (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()

def _machine(tmp_path, *, run=None, reads="stdin", timeout="60", concurrency="2"):
    (tmp_path / "attest.secret").write_text("secret-xyz")
    run = run or [sys.executable, "bin/image-canonicalize",
                  "--max-edge", "2048", "--quality", "82", "--max-pixels", "40000000"]
    lines = ["capabilities:", "  media.image:",
             f"    run: {json.dumps(run)}", f"    reads: {reads}", "    emits: stdout"]
    if timeout is not None:
        lines.append(f"    timeout: {timeout}")
    if concurrency is not None:
        lines.append(f"    concurrency: {concurrency}")
    (tmp_path / "capabilities.yaml").write_text("\n".join(lines) + "\n")
    return tmp_path

def test_verify_and_sign_returns_signed_canonical(tmp_path):
    mr = _machine(tmp_path)
    res = verify_media.verify_and_sign(mr, "read", POLICY, _jpeg(), "image/jpeg")
    assert res["media_type"] == "image/webp"
    data = base64.b64decode(res["data"])
    assert Image.open(io.BytesIO(data)).format == "WEBP"
    attest.verify(attest.load_secret(mr), "read", data, "image/webp", res["signature"])  # trusts

def test_too_large_is_named(tmp_path):
    mr = _machine(tmp_path)
    with pytest.raises(AttachmentError) as e:
        verify_media.verify_and_sign(mr, "read", {"accept": ["image"], "max_bytes": 10}, _jpeg(), "image/jpeg")
    assert e.value.kind == "too_large"

def test_wrong_type_is_named(tmp_path):
    mr = _machine(tmp_path)
    with pytest.raises(AttachmentError) as e:
        verify_media.verify_and_sign(mr, "read", POLICY, b"%PDF-1.7", "application/pdf")
    assert e.value.kind == "wrong_type"

def test_undecodable_is_named(tmp_path):
    mr = _machine(tmp_path)
    with pytest.raises(AttachmentError) as e:
        verify_media.verify_and_sign(mr, "read", POLICY, b"garbage-not-an-image", "image/png")
    assert e.value.kind == "undecodable"


def test_policy_with_only_accept_is_valid_on_the_box_too(tmp_path):
    # The schema requires only `accept`; max_bytes / max_count are optional bounds.
    # The box must read the policy the schema declares, not a stricter private one.
    mr = _machine(tmp_path)
    res = verify_media.verify_and_sign(mr, "read", {"accept": ["image"]}, _jpeg(), "image/jpeg")
    assert res["media_type"] == "image/webp" and res["signature"]


from shapes.corpus.engine.errors import CapabilityError


def test_a_binding_that_does_not_read_stdin_is_a_box_error(tmp_path):
    mr = _machine(tmp_path, reads="envelope")
    with pytest.raises(CapabilityError, match="reads: stdin"):
        verify_media.verify_and_sign(mr, "read", POLICY, _jpeg(), "image/jpeg")


def test_a_binding_without_a_timeout_is_refused(tmp_path):
    mr = _machine(tmp_path, timeout=None)
    with pytest.raises(CapabilityError, match="timeout"):
        verify_media.verify_and_sign(mr, "read", POLICY, _jpeg(), "image/jpeg")


def test_a_decode_past_the_declared_timeout_is_named(tmp_path):
    mr = _machine(tmp_path, run=[sys.executable, "-c", "import time; time.sleep(5)"], timeout="1")
    with pytest.raises(AttachmentError) as exc:
        verify_media.verify_and_sign(mr, "read", POLICY, _jpeg(), "image/jpeg")
    assert exc.value.kind == "undecodable" and "1s" in str(exc.value)


# The bounds are values, not just keys: a null timeout is unbounded, a string one is a
# TypeError after spawn, and a non-positive one blames every upload on the user.
@pytest.mark.parametrize("timeout", ["null", '"60"', "0", "-1", "true"])
def test_a_timeout_that_is_not_a_positive_number_is_a_box_error(tmp_path, timeout):
    mr = _machine(tmp_path, timeout=timeout)
    with pytest.raises(CapabilityError, match="timeout"):
        verify_media.verify_and_sign(mr, "read", POLICY, _jpeg(), "image/jpeg")


@pytest.mark.parametrize("concurrency", [None, "null", "0", "-1", "true", '"2"', "1.5"])
def test_a_concurrency_that_is_not_a_positive_int_is_a_box_error(tmp_path, concurrency):
    mr = _machine(tmp_path, concurrency=concurrency)
    with pytest.raises(CapabilityError, match="concurrency"):
        verify_media.verify_and_sign(mr, "read", POLICY, _jpeg(), "image/jpeg")


def test_media_binding_returns_the_validated_binding(tmp_path):
    binding = verify_media.media_binding(_machine(tmp_path, timeout="1.5", concurrency="3"))
    assert binding["timeout"] == 1.5 and binding["concurrency"] == 3


def test_a_missing_secret_refuses_before_the_canonicalizer_runs(tmp_path):
    marker = tmp_path / "ran"
    mr = _machine(tmp_path, run=[sys.executable, "-c", f"open({str(marker)!r}, 'w')"])
    (mr / "attest.secret").unlink()
    with pytest.raises(attest.AttestError, match="attest secret"):
        verify_media.verify_and_sign(mr, "read", POLICY, _jpeg(), "image/jpeg")
    assert not marker.exists()
