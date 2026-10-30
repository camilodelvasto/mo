"""Tests for incremental build hash diffing."""
import json
from pathlib import Path
from incremental import compute_hashes, diff_hashes, save_manifest, load_manifest


class TestComputeHashes:
    def test_hashes_files(self, tmp_path):
        (tmp_path / "a.md").write_text("hello")
        (tmp_path / "b.md").write_text("world")
        hashes = compute_hashes(tmp_path)
        assert len(hashes) == 2
        assert "a.md" in hashes
        assert "b.md" in hashes
        assert len(hashes["a.md"]) == 64

    def test_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.md").write_text("nested")
        hashes = compute_hashes(tmp_path)
        assert "sub/c.md" in hashes

    def test_deterministic(self, tmp_path):
        (tmp_path / "a.md").write_text("same")
        h1 = compute_hashes(tmp_path)
        h2 = compute_hashes(tmp_path)
        assert h1 == h2


class TestDiffHashes:
    def test_detects_new_file(self):
        old = {"a.md": "aaa"}
        new = {"a.md": "aaa", "b.md": "bbb"}
        changed = diff_hashes(old, new)
        assert "b.md" in changed
        assert "a.md" not in changed

    def test_detects_modified_file(self):
        old = {"a.md": "aaa"}
        new = {"a.md": "bbb"}
        assert "a.md" in diff_hashes(old, new)

    def test_detects_deleted_file(self):
        old = {"a.md": "aaa", "b.md": "bbb"}
        new = {"a.md": "aaa"}
        assert "b.md" in diff_hashes(old, new)

    def test_no_changes(self):
        hashes = {"a.md": "aaa"}
        assert diff_hashes(hashes, hashes) == set()


class TestManifest:
    def test_save_and_load(self, tmp_path):
        hashes = {"a.md": "abc123", "sub/b.md": "def456"}
        manifest = tmp_path / ".grove-hashes"
        save_manifest(hashes, manifest)
        loaded = load_manifest(manifest)
        assert loaded == hashes

    def test_missing_manifest_returns_empty(self, tmp_path):
        loaded = load_manifest(tmp_path / "nonexistent")
        assert loaded == {}
