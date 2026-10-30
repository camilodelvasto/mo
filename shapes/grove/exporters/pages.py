"""Grove page loader — declarative page map.

A grove's `pages:` map (in grove.yaml) maps each exact route to a page-folder location.
Each folder holds a `page.yaml` declaration and optionally its own content (index.html +
styles.css/script.js, referenced as `self`). An absent map → [] (the bare grove renders
its default feed home). Validation is mandatory-and-throws: a declared page must be a
valid page (folder exists, page.yaml present and carries a title) or the build throws.
"""
import yaml
from pathlib import Path


class PageError(Exception):
    """Raised for a missing or invalid declared page."""


def _load_page_folder(page_yaml: Path, route: str, folder: Path, grove: dict) -> dict:
    try:
        decl = yaml.safe_load(page_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PageError(f"page '{route}': malformed page.yaml: {e}") from e
    if not isinstance(decl, dict):
        raise PageError(f"page '{route}': page.yaml must be a mapping")
    if "title" not in decl:
        if route == "/":
            decl["title"] = grove["title"]
        else:
            raise PageError(f"page '{route}': page.yaml missing required 'title'")
    body = decl.get("body", ["self"])
    if not isinstance(body, list):
        raise PageError(f"page '{route}': 'body' must be a list")
    mount = decl.get("mount")
    if mount is not None and mount != "subtree":
        raise PageError(f"page '{route}': 'mount' must be 'subtree' or absent, got {mount!r}")
    # width is ORTHOGONAL to layout: layout decides chrome (header/footer), width decides
    # the content column. They compose freely — e.g. layout: page + width: full = header
    # kept, full bleed. Default content (the article column); never coupled to layout.
    width = decl.get("width", "content")
    if width not in ("content", "full"):
        raise PageError(f"page '{route}': 'width' must be 'content' or 'full', got {width!r}")
    return {
        "route": route,
        "folder": folder,
        "title": decl["title"],
        "layout": decl.get("layout"),
        "width": width,
        "og": decl.get("og"),
        "egress": decl.get("egress"),
        "body": body,
        # None → leaf (exact route). "subtree" → the page owns its prefix; any path
        # under it resolves to this one page, and the mounted feature reads the slug.
        "mount": mount,
        "published": decl.get("published", True),
        "discoverable": decl.get("discoverable", True),
        "excerpt": decl.get("excerpt"),
    }


def _norm(route: str) -> str:
    return route if route == "/" else route.rstrip("/") + "/"


def _assert_one_owner_per_prefix(pages: list[dict]) -> None:
    """A `mount: subtree` page owns its whole prefix — no OTHER declared route (leaf or a
    second mount) may fall under it. That collision is the ambiguity the no-matching rule
    exists to prevent (one declared owner per request), so the build throws naming both.
    The mount-under-mount case is the one most likely to be missed; it must be covered."""
    for m in pages:
        if m.get("mount") != "subtree":
            continue
        base = _norm(m["route"])
        for other in pages:
            if other is m:
                continue
            if _norm(other["route"]).startswith(base):
                raise PageError(
                    f"route '{other['route']}' falls under subtree mount '{m['route']}' "
                    f"— a prefix is owned by one mount")


def load_pages(grove_root, grove: dict) -> list[dict]:
    """Load every page declared in the grove's `pages:` map. Returns [] when absent."""
    pages_map = grove.get("pages")
    if not pages_map:
        return []
    if not isinstance(pages_map, dict):
        raise PageError("grove 'pages' must be a mapping of route -> folder location")
    grove_root = Path(grove_root)
    out = []
    for route, location in pages_map.items():
        if not isinstance(location, str):
            raise PageError(f"page '{route}': value must be a folder location string, got {location!r}")
        folder = grove_root / location
        if not folder.is_dir():
            raise PageError(f"page '{route}': folder '{location}' not found")
        page_yaml = folder / "page.yaml"
        if not page_yaml.is_file():
            raise PageError(f"page '{route}': missing page.yaml in '{location}'")
        out.append(_load_page_folder(page_yaml, route, folder, grove))
    _assert_one_owner_per_prefix(out)
    return out
