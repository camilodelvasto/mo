"""Theme token → CSS pipeline.

Loads `themes/<name>/tokens.yaml` and produces a CSS string that assigns
CSS custom properties to `:root` (light) and `:root[data-theme="dark"]` (dark).

The CSS is injected inline into the page shell so tokens are available
before first paint — no FOUC, no fetch round-trip.
"""
from __future__ import annotations

from pathlib import Path
import yaml


def _collect_vars(tokens: dict) -> list[tuple[str, str]]:
    """Convert a tokens dict into a list of (css-var, value) pairs.

    Mirrors theme.js collectThemeVars():
      - palette entries  → --palette-<name>
      - scalar keys      → --<key>
      - color-* keys     → --<key>-resolved (palette lookup)
    """
    pairs: list[tuple[str, str]] = []
    palette = tokens.get("palette", {}) or {}

    for name, value in palette.items():
        pairs.append((f"--palette-{name}", str(value)))

    for key, value in tokens.items():
        if key == "palette":
            continue
        if isinstance(value, (dict, list)):
            continue
        pairs.append((f"--{key}", str(value)))

    for key, value in tokens.items():
        if key.startswith("color-") and isinstance(value, str):
            if value not in palette:
                raise KeyError(
                    f"Token '{key}' references palette entry '{value}' which is not defined"
                )
            pairs.append((f"--{key}-resolved", str(palette[value])))

    return pairs


def _render_block(selector: str, pairs: list[tuple[str, str]]) -> str:
    lines = "\n".join(f"  {k}: {v};" for k, v in pairs)
    return f"{selector} {{\n{lines}\n}}"


def load_tokens(themes_dir: Path, name: str) -> dict:
    """Load a single tokens.yaml by theme name. Raises if missing."""
    path = themes_dir / name / "tokens.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Theme tokens not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _merge_tokens(base: dict, overlay: dict) -> dict:
    """Deep-merge overlay on top of base. Palette dicts merge; scalars override."""
    merged = {**base}
    for key, value in overlay.items():
        if key == "palette" and isinstance(value, dict):
            merged["palette"] = {**base.get("palette", {}), **value}
        else:
            merged[key] = value
    return merged


def load_theme_overrides(themes_dir: Path, name: str) -> str:
    """Read a theme's structural style.css. Absent = empty string (no overrides).

    Unlike tokens.yaml (required — the shared sheets depend on its vars),
    style.css is purely additive. A missing file means no structural
    overrides; it fabricates no default, so "no fallbacks" is not violated.
    """
    path = themes_dir / name / "style.css"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def render_theme_css(themes_dir: Path) -> str:
    """Produce inline CSS for light+dark tokens. Emits :root and
    :root[data-theme="dark"] selectors.

    Dark inherits from default — only overridden tokens need to be declared.
    Palette entries merge so dark can redefine specific colors without
    repeating the full palette.
    """
    light = load_tokens(themes_dir, "default")
    dark_overrides = load_tokens(themes_dir, "dark")
    dark = _merge_tokens(light, dark_overrides)

    light_block = _render_block(":root", _collect_vars(light))
    dark_block = _render_block(':root[data-theme="dark"]', _collect_vars(dark))

    base = f"{light_block}\n\n{dark_block}\n"

    overrides = "".join(
        load_theme_overrides(themes_dir, name) for name in ("default", "dark")
    )
    if not overrides.strip():
        return base
    return f"{base}\n/* theme structural overrides */\n{overrides}"
