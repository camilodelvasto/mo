"""Tests for deck build — asset encryption and manifest generation."""
import base64
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_build(tmp_path):
    """Create a minimal build directory with media files."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\nfake image")
    (data / "chart.svg").write_text("<svg>chart</svg>")
    sub = data / "nested"
    sub.mkdir()
    (sub / "deep.jpg").write_bytes(b"\xff\xd8\xff\xe0fake jpeg")
    # OG image
    og = tmp_path / "og"
    og.mkdir()
    (og / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\nog image")
    return tmp_path


class TestEncryptAssets:
    def test_encrypts_all_files_in_data(self, tmp_build):
        from build import _encrypt_assets
        mnemonic = "abandon " * 11 + "about"
        salt_b64 = _encrypt_assets(tmp_build, mnemonic)

        # Original files replaced with .enc versions
        assert not (tmp_build / "data" / "photo.png").exists()
        assert (tmp_build / "data" / "photo.png.enc").exists()
        assert not (tmp_build / "data" / "chart.svg").exists()
        assert (tmp_build / "data" / "chart.svg.enc").exists()
        assert not (tmp_build / "data" / "nested" / "deep.jpg").exists()
        assert (tmp_build / "data" / "nested" / "deep.jpg.enc").exists()

        # Envelope structure
        envelope = json.loads((tmp_build / "data" / "photo.png.enc").read_text())
        assert envelope["encrypted"] is True
        assert "salt" in envelope
        assert "iv" in envelope
        assert "payload" in envelope

        # Shared salt across all assets
        assert envelope["salt"] == salt_b64
        other = json.loads((tmp_build / "data" / "chart.svg.enc").read_text())
        assert other["salt"] == salt_b64

        # Different IV per file
        assert envelope["iv"] != other["iv"]

    def test_encrypts_og_directory(self, tmp_build):
        from build import _encrypt_assets
        mnemonic = "abandon " * 11 + "about"
        _encrypt_assets(tmp_build, mnemonic)

        assert not (tmp_build / "og" / "cover.png").exists()
        assert (tmp_build / "og" / "cover.png.enc").exists()

    def test_writes_asset_salt_json(self, tmp_build):
        from build import _encrypt_assets
        mnemonic = "abandon " * 11 + "about"
        salt_b64 = _encrypt_assets(tmp_build, mnemonic)

        salt_file = tmp_build / "asset-salt.json"
        assert salt_file.exists()
        data = json.loads(salt_file.read_text())
        assert data["salt"] == salt_b64

    def test_roundtrip_decrypt(self, tmp_build):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes

        original = (tmp_build / "data" / "photo.png").read_bytes()
        mnemonic = "abandon " * 11 + "about"

        from build import _encrypt_assets
        salt_b64 = _encrypt_assets(tmp_build, mnemonic)

        envelope = json.loads((tmp_build / "data" / "photo.png.enc").read_text())
        salt = base64.b64decode(envelope["salt"])
        iv = base64.b64decode(envelope["iv"])
        ct = base64.b64decode(envelope["payload"])

        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                         salt=salt, iterations=100000)
        key = kdf.derive(mnemonic.encode())
        decrypted = AESGCM(key).decrypt(iv, ct, None)
        assert decrypted == original

    def test_no_data_dir_is_noop(self, tmp_path):
        from build import _encrypt_assets
        mnemonic = "abandon " * 11 + "about"
        salt_b64 = _encrypt_assets(tmp_path, mnemonic)
        assert salt_b64 is not None
        assert (tmp_path / "asset-salt.json").exists()

    def test_returns_collected_asset_paths(self, tmp_build):
        from build import _encrypt_assets, _collect_encrypted_asset_paths
        mnemonic = "abandon " * 11 + "about"
        _encrypt_assets(tmp_build, mnemonic)
        paths = _collect_encrypted_asset_paths(tmp_build)
        # Paths should be the original (pre-encryption) relative paths
        assert "/data/photo.png" in paths
        assert "/data/chart.svg" in paths
        assert "/data/nested/deep.jpg" in paths
        assert "/og/cover.png" in paths


class TestBuildManifest:
    def test_generates_manifest_with_all_files(self, tmp_build):
        """Manifest lists every file in the build directory."""
        from build import _build_manifest

        # Add some more files to simulate a real build
        (tmp_build / "index.html").write_text("<html>deck</html>")
        (tmp_build / "app.js").write_text("// app")
        (tmp_build / "style.css").write_text("/* css */")
        theme = tmp_build / "theme"
        theme.mkdir(exist_ok=True)
        (theme / "tokens.json").write_text('{}')
        fonts = tmp_build / "fonts"
        fonts.mkdir()
        (fonts / "inter.woff2").write_bytes(b"fake font")

        manifest = _build_manifest(tmp_build, "abc123def456")

        assert manifest["version"] == "abc123def456"
        paths = [f["path"] for f in manifest["files"]]
        assert "data/photo.png" in paths
        assert "data/chart.svg" in paths
        assert "data/nested/deep.jpg" in paths
        assert "fonts/inter.woff2" in paths
        assert "index.html" in paths

        # Each entry has size and mime
        for entry in manifest["files"]:
            assert isinstance(entry["size"], int)
            assert isinstance(entry["mime"], str)
            assert entry["size"] > 0

    def test_excludes_sw_and_manifest(self, tmp_build):
        """sw.js and manifest.json should not be in the manifest."""
        from build import _build_manifest

        (tmp_build / "sw.js").write_text("// sw")
        (tmp_build / "manifest.json").write_text("{}")

        manifest = _build_manifest(tmp_build, "abc123")
        paths = [f["path"] for f in manifest["files"]]
        assert "sw.js" not in paths
        assert "manifest.json" not in paths

    def test_mime_detection(self, tmp_build):
        from build import _build_manifest

        manifest = _build_manifest(tmp_build, "abc123")
        by_path = {f["path"]: f for f in manifest["files"]}
        assert by_path["data/photo.png"]["mime"] == "image/png"
        assert by_path["data/chart.svg"]["mime"] == "image/svg+xml"
        assert by_path["data/nested/deep.jpg"]["mime"] == "image/jpeg"


class TestLocalFirstSentinel:
    def test_local_first_false_by_default(self, tmp_path):
        """When local_first=False, sw.js should have LOCAL_FIRST = false."""
        sw_content = (
            "const BUILD_VERSION = 'dev';\n"
            "const LOCAL_FIRST = false;\n"
            "const PRECACHE_CONTENT = [];\n"
            "const OWNED_SPA_ROOTS = [];\n"
            "const OWNED_ASSETS = [];\n"
        )
        (tmp_path / "sw.js").write_text(sw_content)

        from build import _inject_local_first
        _inject_local_first(tmp_path, False)

        result = (tmp_path / "sw.js").read_text()
        assert "const LOCAL_FIRST = false;" in result

    def test_local_first_true_injected(self, tmp_path):
        """When local_first=True, sw.js should have LOCAL_FIRST = true."""
        sw_content = (
            "const BUILD_VERSION = 'dev';\n"
            "const LOCAL_FIRST = false;\n"
            "const PRECACHE_CONTENT = [];\n"
            "const OWNED_SPA_ROOTS = [];\n"
            "const OWNED_ASSETS = [];\n"
        )
        (tmp_path / "sw.js").write_text(sw_content)

        from build import _inject_local_first
        _inject_local_first(tmp_path, True)

        result = (tmp_path / "sw.js").read_text()
        assert "const LOCAL_FIRST = true;" in result
        assert "const LOCAL_FIRST = false;" not in result
