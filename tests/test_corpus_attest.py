import pytest
from shapes.corpus.access import attest

SECRET = b"unit-test-secret"

def test_sign_verify_roundtrip():
    data = b"\x89PNG canonical bytes"
    import hashlib
    sig = attest.sign(SECRET, "read", hashlib.sha256(data).hexdigest(), "image/webp")
    attest.verify(SECRET, "read", data, "image/webp", sig)  # no raise

def test_tampered_bytes_fail():
    import hashlib
    sig = attest.sign(SECRET, "read", hashlib.sha256(b"abc").hexdigest(), "image/webp")
    with pytest.raises(attest.AttestError):
        attest.verify(SECRET, "read", b"abcd", "image/webp", sig)

def test_media_type_is_bound():
    import hashlib
    sig = attest.sign(SECRET, "read", hashlib.sha256(b"abc").hexdigest(), "image/webp")
    with pytest.raises(attest.AttestError):
        attest.verify(SECRET, "read", b"abc", "image/png", sig)

def test_load_secret_missing_throws(tmp_path):
    with pytest.raises(attest.AttestError):
        attest.load_secret(tmp_path)

def test_load_secret_empty_throws(tmp_path):
    (tmp_path / "attest.secret").write_text("   ")
    with pytest.raises(attest.AttestError):
        attest.load_secret(tmp_path)

def test_load_secret_reads_bytes(tmp_path):
    (tmp_path / "attest.secret").write_text("hunter2\n")
    assert attest.load_secret(tmp_path) == b"hunter2"

@pytest.mark.parametrize("sig", ["é", "", "abc", "Z" * 64, None, 42])
def test_a_malformed_signature_is_refused_as_such(sig):
    with pytest.raises(attest.AttestError, match="64-hex"):
        attest.verify(SECRET, "read", b"abc", "image/webp", sig)

def test_a_token_issued_for_one_ask_does_not_verify_on_another():
    import hashlib
    data = b"abc"
    sig = attest.sign(SECRET, "read", hashlib.sha256(data).hexdigest(), "image/webp")
    attest.verify(SECRET, "read", data, "image/webp", sig)          # no raise
    with pytest.raises(attest.AttestError):
        attest.verify(SECRET, "other", data, "image/webp", sig)
