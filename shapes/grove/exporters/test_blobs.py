"""Tests for content-addressed blob writing."""
import hashlib
from pathlib import Path
from blobs import write_blobs, content_hash


def test_content_hash_deterministic():
    assert content_hash("hello") == content_hash("hello")


def test_content_hash_is_16_hex_chars():
    h = content_hash("hello world")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_content_hash_uses_sha256():
    text = "hello world"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    assert content_hash(text) == expected


def test_write_blobs_creates_files(tmp_path):
    pages = {
        "/": "<html>index</html>",
        "/welcome/": "<html>welcome</html>",
    }
    blobs_dir = tmp_path / "blobs"
    result = write_blobs(pages, blobs_dir)

    assert blobs_dir.is_dir()
    assert len(list(blobs_dir.iterdir())) == 2
    for route, entry in result.items():
        blob_path = blobs_dir / entry["blob"]
        assert blob_path.exists()
        assert blob_path.read_text(encoding="utf-8") == pages[route]


def test_write_blobs_returns_mapping(tmp_path):
    pages = {"/": "<html>index</html>"}
    result = write_blobs(pages, tmp_path / "blobs")

    assert "/" in result
    entry = result["/"]
    assert "blob" in entry
    assert "hash" in entry
    assert entry["blob"].endswith(".bin")
    assert entry["blob"].startswith(entry["hash"][:16])


def test_write_blobs_different_content_different_names(tmp_path):
    pages = {
        "/a/": "<html>page a</html>",
        "/b/": "<html>page b</html>",
    }
    result = write_blobs(pages, tmp_path / "blobs")
    assert result["/a/"]["blob"] != result["/b/"]["blob"]


def test_write_blobs_same_content_same_name(tmp_path):
    pages = {
        "/a/": "<html>same</html>",
        "/b/": "<html>same</html>",
    }
    result = write_blobs(pages, tmp_path / "blobs")
    assert result["/a/"]["blob"] == result["/b/"]["blob"]
    # Only one file written for deduplicated content
    blobs_dir = tmp_path / "blobs"
    assert len(list(blobs_dir.iterdir())) == 1
