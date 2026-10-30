"""Vet authored element markup against a declared allowlist and reject every
external reference. Throws on violation (no strip-and-continue). `allowed_origins`
widens what passes — it is the page's computed egress grant.

The allowlist is a declared registry (config/html-allowlist.json), not hardcoded.
"""
import functools
import json
import re
from html.parser import HTMLParser
from pathlib import Path

_ALLOWLIST_PATH = Path(__file__).resolve().parent.parent / "config" / "html-allowlist.json"
# Matches url() capturing the URL inside (optional quotes, optional whitespace).
_CSS_URL_EXTRACT_RE = re.compile(r"""url\(\s*['"]?\s*((?:[a-z][a-z0-9+.-]*:)?//[^'"\s)]*)\s*['"]?\s*\)""", re.I)
# Matches @import with an absolute or protocol-relative URL.
_CSS_IMPORT_RE = re.compile(r"""@import\s+(?:url\(\s*)?['"]?\s*(?:[a-z][a-z0-9+.-]*:)?//""", re.I)

# Protocols that are always disallowed regardless of origin grants.
_DISALLOWED_PROTOCOLS_RE = re.compile(r"^(javascript|vbscript)\s*:", re.I)
# data: URIs are allowed only for images; everything else is disallowed.
_DATA_URI_RE = re.compile(r"^data\s*:", re.I)
_DATA_IMAGE_RE = re.compile(r"^data\s*:\s*image/", re.I)


class VetError(Exception):
    """Raised when markup violates the allowlist or references an undeclared external origin."""


@functools.lru_cache(maxsize=1)
def _load_allowlist() -> dict:
    raw = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    # Normalize attribute names to lowercase so HTMLParser's lowercased names
    # match the allowlist regardless of how the JSON was authored.
    raw["global_attrs"] = [a.lower() for a in raw["global_attrs"]]
    raw["tag_attrs"] = {
        tag: [a.lower() for a in attrs]
        for tag, attrs in raw["tag_attrs"].items()
    }
    return raw


def _origin_allowed(url: str, allowed_origins) -> bool:
    for origin in allowed_origins:
        if url.startswith(origin):
            # Require the next char after the prefix to be a boundary character
            # (or end of string) to prevent subdomain-prefix bypass.
            rest = url[len(origin):]
            if not rest or rest[0] in ("/#?"):
                return True
    return False


def _check_protocol(value: str, tag: str = "", attr: str = "") -> None:
    """Raise VetError for disallowed protocols in an attribute value."""
    v = value.strip()
    if _DISALLOWED_PROTOCOLS_RE.match(v):
        proto = v.split(":")[0].lower()
        raise VetError(f"disallowed protocol '{proto}:' in <{tag} {attr}>: {value}")
    if _DATA_URI_RE.match(v) and not _DATA_IMAGE_RE.match(v):
        raise VetError(f"disallowed data: URI (only data:image/ is allowed) in <{tag} {attr}>: {value[:60]}")


def _is_external(value: str) -> bool:
    v = value.strip()
    return v.startswith("//") or bool(re.match(r"^[a-z][a-z0-9+.-]*://", v, re.I))


class _Vetter(HTMLParser):
    def __init__(self, allowlist: dict, allowed_origins):
        super().__init__(convert_charrefs=True)
        self.allowlist = allowlist
        self.allowed_origins = list(allowed_origins)
        self.global_attrs = allowlist["global_attrs"]
        self.tag_attrs = allowlist["tag_attrs"]
        self.tags = set(allowlist["tags"])
        self._in_style = False

    def _attr_allowed(self, tag: str, name: str) -> bool:
        for ga in self.global_attrs:
            if ga.endswith("-*") and name.startswith(ga[:-1]):
                return True
            if name == ga:
                return True
        return name in self.tag_attrs.get(tag, [])

    def handle_starttag(self, tag, attrs):
        # <link> is always an external stylesheet pull — disallowed with a clear message.
        if tag == "link":
            raise VetError("disallowed <link> (external stylesheets are not allowed)")

        # <script> with an external src is an external reference; without src it is
        # still disallowed — authored logic belongs in the element's script.js.
        if tag == "script":
            for name, value in attrs:
                if name == "src" and value and _is_external(value) and not _origin_allowed(value, self.allowed_origins):
                    raise VetError(f"external script src is not allowed: {value}")
            raise VetError("authored markup may not contain <script>; use the element's script.js")

        if tag not in self.tags:
            raise VetError(f"disallowed tag <{tag}>")

        if tag == "style":
            self._in_style = True

        for name, value in attrs:
            if name.startswith("on"):
                raise VetError(f"inline event handler '{name}' is not allowed; wire events in script.js")
            if not self._attr_allowed(tag, name):
                raise VetError(f"disallowed attribute '{name}' on <{tag}>")
            if value:
                _check_protocol(value, tag=tag, attr=name)
                if _is_external(value) and not _origin_allowed(value, self.allowed_origins):
                    raise VetError(f"external reference in <{tag} {name}>: {value}")

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        # Only inspect CSS text (inside <style> tags or style attributes).
        # HTMLParser calls handle_data for all text nodes; we want to catch
        # CSS @import and url() references inside <style> blocks.
        if not self._in_style:
            return
        for match in _CSS_URL_EXTRACT_RE.finditer(data):
            url = match.group(1)
            if not _origin_allowed(url, self.allowed_origins):
                raise VetError(f"external CSS url() reference: {url[:60]}")
        if _CSS_IMPORT_RE.search(data):
            raise VetError("external @import is not allowed")


def vet_html(html: str, *, allowed_origins=()) -> None:
    """Validate markup. Raise VetError on the first violation. Return None on success."""
    allowlist = _load_allowlist()
    _Vetter(allowlist, allowed_origins).feed(html)
