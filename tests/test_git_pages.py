"""Tests for git_pages merge and manifest logic."""
import tempfile
from pathlib import Path

from shapes.shared.git_pages import _merge_into_subdirectory, _manifest_path


def _setup(tmp_path):
    """Create work_dir and dist_path in a temp directory."""
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    (work_dir / ".git").mkdir()
    dist_path = tmp_path / "dist"
    dist_path.mkdir()
    return work_dir, dist_path


class TestRootDeployPreservesSubdirectories:
    def test_root_deploy_does_not_wipe_subdirectory_deploy(self, tmp_path):
        work_dir, dist_path = _setup(tmp_path)

        # Simulate a prior subdirectory deploy at /decks/pitch
        decks_dir = work_dir / "decks" / "pitch"
        decks_dir.mkdir(parents=True)
        (decks_dir / "index.html").write_text("<h1>Pitch</h1>")
        manifest = _manifest_path(work_dir, "/decks/pitch")
        manifest.write_text("decks\n")

        # Now do a root deploy
        (dist_path / "index.html").write_text("<h1>Grove</h1>")
        (dist_path / "style.css").write_text("body {}")
        _merge_into_subdirectory(dist_path, work_dir, "/")

        # Root content is there
        assert (work_dir / "index.html").read_text() == "<h1>Grove</h1>"
        assert (work_dir / "style.css").read_text() == "body {}"

        # Subdirectory deploy survived
        assert (work_dir / "decks" / "pitch" / "index.html").read_text() == "<h1>Pitch</h1>"

    def test_root_deploy_cleans_old_root_files(self, tmp_path):
        work_dir, dist_path = _setup(tmp_path)

        # First root deploy
        (dist_path / "old.css").write_text("old")
        _merge_into_subdirectory(dist_path, work_dir, "/")
        assert (work_dir / "old.css").exists()

        # Second root deploy without old.css
        dist_path2 = tmp_path / "dist2"
        dist_path2.mkdir()
        (dist_path2 / "new.css").write_text("new")
        _merge_into_subdirectory(dist_path2, work_dir, "/")

        assert (work_dir / "new.css").exists()
        assert not (work_dir / "old.css").exists()

    def test_subdirectory_deploy_does_not_affect_root(self, tmp_path):
        work_dir, dist_path = _setup(tmp_path)

        # Root deploy first
        (dist_path / "index.html").write_text("<h1>Grove</h1>")
        _merge_into_subdirectory(dist_path, work_dir, "/")

        # Subdirectory deploy
        deck_dist = tmp_path / "deck_dist"
        deck_dist.mkdir()
        (deck_dist / "index.html").write_text("<h1>Pitch</h1>")
        _merge_into_subdirectory(deck_dist, work_dir, "/decks/pitch")

        # Both exist
        assert (work_dir / "index.html").read_text() == "<h1>Grove</h1>"
        assert (work_dir / "decks" / "pitch" / "index.html").read_text() == "<h1>Pitch</h1>"

    def test_root_redeploy_after_subdirectory_preserves_subdirectory(self, tmp_path):
        work_dir, dist_path = _setup(tmp_path)

        # Root deploy
        (dist_path / "index.html").write_text("<h1>Grove</h1>")
        _merge_into_subdirectory(dist_path, work_dir, "/")

        # Subdirectory deploy
        deck_dist = tmp_path / "deck_dist"
        deck_dist.mkdir()
        (deck_dist / "index.html").write_text("<h1>Pitch</h1>")
        _merge_into_subdirectory(deck_dist, work_dir, "/decks/pitch")

        # Root redeploy — the critical test
        dist_path2 = tmp_path / "dist2"
        dist_path2.mkdir()
        (dist_path2 / "index.html").write_text("<h1>Grove v2</h1>")
        _merge_into_subdirectory(dist_path2, work_dir, "/")

        assert (work_dir / "index.html").read_text() == "<h1>Grove v2</h1>"
        assert (work_dir / "decks" / "pitch" / "index.html").read_text() == "<h1>Pitch</h1>"


class TestManifests:
    def test_root_deploy_writes_manifest(self, tmp_path):
        work_dir, dist_path = _setup(tmp_path)
        (dist_path / "index.html").write_text("hi")
        _merge_into_subdirectory(dist_path, work_dir, "/")

        manifest = _manifest_path(work_dir, "/")
        assert manifest.exists()
        entries = set(manifest.read_text().splitlines())
        assert "index.html" in entries

    def test_subdirectory_deploy_writes_manifest(self, tmp_path):
        work_dir, dist_path = _setup(tmp_path)
        (dist_path / "index.html").write_text("hi")
        _merge_into_subdirectory(dist_path, work_dir, "/decks/pitch")

        manifest = _manifest_path(work_dir, "/decks/pitch")
        assert manifest.exists()
        entries = set(manifest.read_text().splitlines())
        assert "decks" in entries
