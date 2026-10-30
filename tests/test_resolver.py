"""Tests for the path-based theme resolver."""
from pathlib import Path

import pytest

from cli.resolver import resolve_theme_dir


def test_resolve_theme_dir_returns_absolute_path(tmp_path):
    theme_dir = tmp_path / "themes" / "pitch"
    theme_dir.mkdir(parents=True)
    (theme_dir / "tokens.yaml").write_text("palette: {}")

    content_file = tmp_path / "deck.yaml"
    content_file.write_text("theme: themes/pitch")

    result = resolve_theme_dir("themes/pitch", content_file)
    assert result == theme_dir.resolve()
    assert result.is_absolute()


def test_resolve_theme_dir_navigates_up(tmp_path):
    shared = tmp_path / "shared-themes" / "dark"
    shared.mkdir(parents=True)
    (shared / "tokens.yaml").write_text("palette: {}")

    content_dir = tmp_path / "content" / "decks"
    content_dir.mkdir(parents=True)
    content_file = content_dir / "deck.yaml"
    content_file.write_text("theme: ../../shared-themes/dark")

    result = resolve_theme_dir("../../shared-themes/dark", content_file)
    assert result == shared.resolve()


def test_resolve_theme_dir_raises_when_missing(tmp_path):
    content_file = tmp_path / "deck.yaml"
    content_file.write_text("theme: themes/nonexistent")

    with pytest.raises(FileNotFoundError, match="nonexistent"):
        resolve_theme_dir("themes/nonexistent", content_file)


def test_resolve_theme_dir_raises_when_file_not_dir(tmp_path):
    not_a_dir = tmp_path / "themes" / "pitch"
    not_a_dir.parent.mkdir(parents=True)
    not_a_dir.write_text("i am a file")

    content_file = tmp_path / "deck.yaml"
    content_file.write_text("theme: themes/pitch")

    with pytest.raises(FileNotFoundError):
        resolve_theme_dir("themes/pitch", content_file)
