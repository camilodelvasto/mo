"""Icon catalog — loads SVG by id from shapes/grove/icons/."""
from __future__ import annotations

from pathlib import Path


def load_icon(icon_id: str, icons_dir: Path) -> str:
    """Load an SVG icon by id. Raises FileNotFoundError for unknown ids."""
    path = icons_dir / f"{icon_id}.svg"
    if not path.exists():
        raise FileNotFoundError(
            f"Unknown icon '{icon_id}'. Available: "
            + ", ".join(p.stem for p in sorted(icons_dir.glob("*.svg")))
        )
    return path.read_text(encoding="utf-8").strip()
