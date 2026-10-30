"""Tests for grove encryption module."""
import base64
import json
from encrypt import make_encryptor, make_asset_encryptor, generate_mnemonic


class TestGenerateMnemonic:
    def test_returns_12_words(self):
        phrase = generate_mnemonic()
        words = phrase.split()
        assert len(words) == 12

    def test_different_each_call(self):
        a = generate_mnemonic()
        b = generate_mnemonic()
        assert a != b


class TestMakeEncryptor:
    def test_returns_callable(self):
        enc = make_encryptor("abandon " * 11 + "about")
        assert callable(enc)

    def test_envelope_structure(self):
        mnemonic = generate_mnemonic()
        enc = make_encryptor(mnemonic)
        envelope_json = enc("<p>Secret content</p>", {"title": "Test Post"})
        envelope = json.loads(envelope_json)
        assert envelope["encrypted"] is True
        assert envelope["key_id"] is None
        assert envelope["meta"]["title"] == "Test Post"
        assert "salt" in envelope
        assert "iv" in envelope
        assert "payload" in envelope

    def test_roundtrip_with_web_crypto_params(self):
        """Verify the envelope can be decrypted with the same parameters."""
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes

        mnemonic = generate_mnemonic()
        enc = make_encryptor(mnemonic)
        original = "<main><h1>Hello</h1><p>Secret</p></main>"
        envelope_json = enc(original, {"title": "RT"})
        envelope = json.loads(envelope_json)

        salt = base64.b64decode(envelope["salt"])
        iv = base64.b64decode(envelope["iv"])
        ct = base64.b64decode(envelope["payload"])

        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                         salt=salt, iterations=100000)
        key = kdf.derive(mnemonic.encode())
        plaintext = AESGCM(key).decrypt(iv, ct, None)
        assert plaintext.decode() == original

    def test_different_salt_per_call(self):
        mnemonic = generate_mnemonic()
        enc = make_encryptor(mnemonic)
        a = json.loads(enc("a", {"title": "A"}))
        b = json.loads(enc("b", {"title": "B"}))
        assert a["salt"] != b["salt"]
        assert a["iv"] != b["iv"]


class TestMakeAssetEncryptor:
    def test_returns_callable_and_salt(self):
        mnemonic = generate_mnemonic()
        encryptor, salt_b64 = make_asset_encryptor(mnemonic)
        assert callable(encryptor)
        assert isinstance(salt_b64, str)
        assert len(base64.b64decode(salt_b64)) == 16

    def test_envelope_structure(self):
        mnemonic = generate_mnemonic()
        encryptor, salt_b64 = make_asset_encryptor(mnemonic)
        data = b"\x89PNG\r\n\x1a\nfake image bytes"
        envelope_json = encryptor(data)
        envelope = json.loads(envelope_json)
        assert envelope["encrypted"] is True
        assert envelope["salt"] == salt_b64
        assert "iv" in envelope
        assert "payload" in envelope

    def test_same_salt_across_calls(self):
        mnemonic = generate_mnemonic()
        encryptor, salt_b64 = make_asset_encryptor(mnemonic)
        a = json.loads(encryptor(b"file1"))
        b = json.loads(encryptor(b"file2"))
        assert a["salt"] == b["salt"] == salt_b64
        assert a["iv"] != b["iv"]

    def test_roundtrip(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes

        mnemonic = generate_mnemonic()
        encryptor, salt_b64 = make_asset_encryptor(mnemonic)
        original = b"\x00\x01\x02\xff" * 100
        envelope = json.loads(encryptor(original))

        salt = base64.b64decode(envelope["salt"])
        iv = base64.b64decode(envelope["iv"])
        ct = base64.b64decode(envelope["payload"])
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                         salt=salt, iterations=100000)
        key = kdf.derive(mnemonic.encode())
        decrypted = AESGCM(key).decrypt(iv, ct, None)
        assert decrypted == original
