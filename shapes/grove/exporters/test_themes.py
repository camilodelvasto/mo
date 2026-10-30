"""Tests for the theme token + structural-override resolver."""
from pathlib import Path

from themes import render_theme_css, load_theme_overrides

_TOKENS = """\
palette:
  ink: "#111111"
color-text: ink
"""


def _write_theme(themes_dir: Path, name: str, style_css: str | None = None) -> None:
    """Scaffold themes_dir/<name>/ with required tokens.yaml and optional style.css."""
    d = themes_dir / name
    d.mkdir(parents=True)
    (d / "tokens.yaml").write_text(_TOKENS, encoding="utf-8")
    if style_css is not None:
        (d / "style.css").write_text(style_css, encoding="utf-8")


def test_load_theme_overrides_returns_contents_when_present(tmp_path):
    _write_theme(tmp_path, "default", style_css='[data-theme="default"] .card { gap: 2rem; }')
    assert load_theme_overrides(tmp_path, "default") == '[data-theme="default"] .card { gap: 2rem; }'


def test_load_theme_overrides_returns_empty_when_absent(tmp_path):
    _write_theme(tmp_path, "default")  # no style.css
    assert load_theme_overrides(tmp_path, "default") == ""


def test_render_appends_both_overrides_after_token_blocks(tmp_path):
    _write_theme(tmp_path, "default", style_css='[data-theme="default"] .x { color: red; }')
    _write_theme(tmp_path, "dark", style_css='[data-theme="dark"] .x { color: blue; }')

    css = render_theme_css(tmp_path)

    # token blocks still present
    assert ":root {" in css
    assert ':root[data-theme="dark"] {' in css
    # both overrides appended, verbatim, after the token blocks
    assert '[data-theme="default"] .x { color: red; }' in css
    assert '[data-theme="dark"] .x { color: blue; }' in css
    assert css.index(":root {") < css.index('[data-theme="default"] .x')
    assert css.index(':root[data-theme="dark"] {') < css.index('[data-theme="default"] .x')


def test_render_omits_override_section_when_absent(tmp_path):
    _write_theme(tmp_path, "default")
    _write_theme(tmp_path, "dark")

    css = render_theme_css(tmp_path)

    assert "theme structural overrides" not in css
    # nothing beyond the two token blocks
    assert css.strip().endswith("}")


def test_render_treats_empty_style_css_as_absent(tmp_path):
    _write_theme(tmp_path, "default", style_css="")
    _write_theme(tmp_path, "dark", style_css="")
    css = render_theme_css(tmp_path)
    assert "theme structural overrides" not in css
    assert css.strip().endswith("}")
