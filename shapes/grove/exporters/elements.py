"""Element resolver. Maps a body item to the one fragment contract:
  - built-in            (header, footer, grid, ...)
  - {feature: id}       -> feature mount marker
  - {builtin: config}   -> a built-in with explicit config
  - "self"              -> this page folder's index.html
  - "elements/<name>"   -> a shared element folder
  - "<builtin>"         -> a built-in (grid, ...)
Unknown name -> ResolveError. Authored elements are vetted then scoped.
"""
import re
from html import escape
from pathlib import Path

from builtins_grove import BUILTINS, is_builtin
from element_vet import vet_html
from element_scope import scope_token, scope_css

# Matches the opening tag of the first element, quote-aware so a literal '>'
# inside an attribute value (e.g. data-x="a>b") is not treated as tag close.
_FIRST_TAG_RE = re.compile(
    r'^(<\w[^>]*?(?:"[^"]*"|\'[^\']*\'|[^>"\'])*?)>',
    re.DOTALL,
)

# Root-relative href/src in authored HTML carry the grove base_path, exactly like
# header actions (components.py) and chat avatars (chat_config.py). Absolute
# (scheme://) and protocol-relative (//) URLs are left untouched.
_ROOT_URL_ATTR_RE = re.compile(r'\b(href|src)="(/(?!/)[^"]*)"')


def _prefix_authored_urls(html: str, base_path: str) -> str:
    prefix = base_path.rstrip("/")
    if not prefix:
        return html
    return _ROOT_URL_ATTR_RE.sub(lambda m: f'{m.group(1)}="{prefix}{m.group(2)}"', html)


class ResolveError(Exception):
    """Raised when a body item names no built-in, no authored element, and no feature."""


def _feature_marker(feature_id: str, grove: dict, page_route: str) -> str:
    for f in grove.get("features", []):
        if f.get("id") == feature_id:
            ask = f.get("ask")
            if ask is None:
                raise ResolveError(f"feature '{feature_id}' declares no 'ask'")
            # data-route is the MOUNTING PAGE's route (trailing slash). The feature is
            # routeless; the page it mounts on owns the prefix, and the chat reads the
            # slug from the path below it (the page declares mount: subtree). The client
            # requires data-route — a routed chat with none throws (no-fallbacks).
            base = page_route.rstrip("/") + "/"
            return (f'<div data-chat-root data-ask="{escape(ask)}" '
                    f'data-route="{escape(base)}"></div>')
    raise ResolveError(f"unknown element 'feature: {feature_id}' — no such feature in grove.yaml")


def emit_authored(source_folder, *, allowed_origins=(), base_path="") -> tuple:
    """Read <source_folder>/index.html (+ styles.css/script.js), vet, scope, return
    (fragment, script_or_None). Used for both shared elements and a page's `self`.
    Root-relative href/src are prefixed with base_path (deploy-subpath safe)."""
    source_folder = Path(source_folder)
    index = source_folder / "index.html"
    if not index.is_file():
        raise ResolveError(f"no index.html in {source_folder}")
    html = index.read_text(encoding="utf-8").strip()
    vet_html(html, allowed_origins=allowed_origins)
    html = _prefix_authored_urls(html, base_path)

    token = scope_token(str(source_folder), html)
    css_file = source_folder / "styles.css"
    style = ""
    if css_file.is_file():
        scoped = scope_css(css_file.read_text(encoding="utf-8"), token)
        style = f'<style>{scoped}</style>'
    m = _FIRST_TAG_RE.match(html)
    if m:
        stamped = f'{m.group(1)} data-{token}>{html[m.end():]}'
    else:
        stamped = f'<div data-{token}>{html}</div>'
    script = None
    script_tag = ""
    script_file = source_folder / "script.js"
    if script_file.is_file():
        script = script_file.read_text(encoding="utf-8")
        script_tag = f'<script type="module">{script}</script>'
    return f'{style}{stamped}{script_tag}', script


def resolve_element(item, grove, ctx, *, grove_root, page_folder, page_route, posts, allowed_origins=()):
    """Resolve one body item to (fragment, script_or_None).

    item forms:
      {feature: id}      -> feature marker
      {builtin: config}  -> a built-in with config
      "self"             -> this page folder's index.html
      "elements/<name>"  -> a shared element folder
      "<builtin>"        -> a built-in (grid, ...)
    Anything else -> ResolveError."""
    if isinstance(item, dict):
        if "feature" in item:
            return _feature_marker(item["feature"], grove, page_route), None
        if len(item) == 1:
            (name, config), = item.items()
            if is_builtin(name):
                return BUILTINS[name](config or {}, grove, ctx, posts=posts), None
            raise ResolveError(f"unknown built-in '{name}'")
        raise ResolveError(f"unrecognized body item: {item!r}")
    if item == "self":
        if page_folder is None:
            raise ResolveError("'self' used outside a page folder")
        return emit_authored(page_folder, allowed_origins=allowed_origins,
                             base_path=ctx["base_path"])
    if item.startswith("elements/"):
        return emit_authored(Path(grove_root) / item, allowed_origins=allowed_origins,
                             base_path=ctx["base_path"])
    if is_builtin(item):
        return BUILTINS[item]({}, grove, ctx, posts=posts), None
    raise ResolveError(f"unknown element '{item}'")
