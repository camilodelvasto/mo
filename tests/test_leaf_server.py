"""Tests for the leaf server scaffold — re-exports the path-based theme resolver."""

from pathlib import Path

import pytest

import importlib.util

ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = ROOT / "shapes" / "leaf" / "renderer" / "shell-web" / "server.py"

spec = importlib.util.spec_from_file_location("leaf_server", SERVER_PATH)
leaf_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leaf_server)


def test_resolve_theme_dir_exported():
    assert hasattr(leaf_server, "resolve_theme_dir")
    assert callable(leaf_server.resolve_theme_dir)


def test_resolve_theme_dir_resolves_relative_path(tmp_path):
    theme_dir = tmp_path / "themes" / "default"
    theme_dir.mkdir(parents=True)
    (theme_dir / "tokens.yaml").write_text("colors: {}")

    content_file = tmp_path / "page.yaml"
    content_file.write_text("theme: themes/default")

    result = leaf_server.resolve_theme_dir("themes/default", content_file)
    assert result == theme_dir.resolve()


def test_resolve_theme_dir_raises_when_missing(tmp_path):
    content_file = tmp_path / "page.yaml"
    content_file.write_text("theme: themes/gone")

    with pytest.raises(FileNotFoundError, match="gone"):
        leaf_server.resolve_theme_dir("themes/gone", content_file)
