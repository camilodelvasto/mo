"""Tests for the shared font utilities."""
from pathlib import Path

import pytest


def test_parse_font_filename_variable():
    from cli.fonts import parse_font_filename
    assert parse_font_filename("Montserrat-Variable") == ("100 900", "normal")


def test_parse_font_filename_regular():
    from cli.fonts import parse_font_filename
    assert parse_font_filename("Lato-Regular") == ("400", "normal")


def test_parse_font_filename_bold():
    from cli.fonts import parse_font_filename
    assert parse_font_filename("Lato-Bold") == ("700", "normal")


def test_parse_font_filename_italic():
    from cli.fonts import parse_font_filename
    assert parse_font_filename("Lato-Italic") == ("400", "italic")


def test_parse_font_filename_bolditalic_not_shadowed_by_bold():
    from cli.fonts import parse_font_filename
    assert parse_font_filename("Lato-BoldItalic") == ("700", "italic")


def test_parse_font_filename_raises_on_unknown_suffix():
    from cli.fonts import parse_font_filename
    with pytest.raises(ValueError, match="Unrecognized font filename suffix"):
        parse_font_filename("Montserrat-Medium")


def test_build_fonts_css_generates_font_face_rules(tmp_path):
    from cli.fonts import build_fonts_css

    family_dir = tmp_path / "inter"
    family_dir.mkdir()
    (family_dir / "Inter-Variable.woff2").write_bytes(b"fake")
    (family_dir / "Inter-Bold.woff2").write_bytes(b"fake")

    css = build_fonts_css(tmp_path)
    assert "@font-face" in css
    assert "font-family: inter" in css
    assert "Inter-Variable.woff2" in css
    assert "font-weight: 100 900" in css
    assert "Inter-Bold.woff2" in css
    assert "font-weight: 700" in css


def test_build_fonts_css_raises_if_dir_missing(tmp_path):
    from cli.fonts import build_fonts_css
    with pytest.raises(FileNotFoundError):
        build_fonts_css(tmp_path / "nonexistent")
