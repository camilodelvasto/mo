"""Tests for grove icon catalog."""
import pytest
from pathlib import Path

from icons import load_icon


@pytest.fixture
def icons_dir(tmp_path):
    d = tmp_path / "icons"
    d.mkdir()
    (d / "search.svg").write_text('<svg aria-hidden="true"><circle/></svg>')
    return d


class TestLoadIcon:
    def test_loads_existing_icon(self, icons_dir):
        svg = load_icon("search", icons_dir)
        assert "<svg" in svg
        assert "<circle/>" in svg

    def test_unknown_icon_throws(self, icons_dir):
        with pytest.raises(FileNotFoundError, match="nope"):
            load_icon("nope", icons_dir)
