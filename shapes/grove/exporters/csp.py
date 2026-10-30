"""Per-page Content-Security-Policy, computed from the page's declarations.

Default: fully locked down. A feature referenced in `body:` (single source of truth) or
listed in `egress.features` (ambient, head-mounted) grants its resolved service origin to
connect-src. forms/embeds directives are computed from `egress` but provider resolution is
a later batch — here an explicit `endpoint` widens form-action/connect-src and an explicit
`origin` widens frame-src.
"""

import re

_SAFE_SOURCE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://[^\s;'\"]+$")


def _safe_source(value: str) -> str:
    """Raise ValueError if value cannot be safely embedded in a CSP directive."""
    if not isinstance(value, str) or not _SAFE_SOURCE_RE.match(value):
        raise ValueError(
            f"unsafe CSP source (must be scheme://host, no spaces/;): {value!r}"
        )
    return value


def _body_feature_ids(page: dict) -> list[str]:
    ids = []
    for item in page.get("body", []):
        if isinstance(item, dict) and "feature" in item:
            ids.append(item["feature"])
    return ids


def compute_csp(page: dict, grove: dict, *, feature_endpoints: dict, script_hashes=()) -> str:
    """Return the CSP value for one page. feature_endpoints maps a feature id to its
    resolved service origin (from the infrastructure target). script_hashes is an
    iterable of 'sha256-…' tokens; when non-empty a script-src directive is appended
    that allows exactly those inline scripts (and nothing else beyond 'self')."""
    egress = page.get("egress") or {}

    feature_ids = list(_body_feature_ids(page))
    for fid in egress.get("features", []):
        if fid not in feature_ids:
            feature_ids.append(fid)

    connect = []
    for fid in feature_ids:
        origin = feature_endpoints.get(fid)
        if origin is None:
            raise KeyError(f"feature '{fid}' used on page has no resolved endpoint")
        origin = _safe_source(origin)
        if origin not in connect:
            connect.append(origin)

    form_action = []
    for form in egress.get("forms", []):
        ep = form.get("endpoint")
        if ep:
            ep = _safe_source(ep)
            if ep not in form_action:
                form_action.append(ep)
            if ep not in connect:
                connect.append(ep)

    frame_src = []
    for embed in egress.get("embeds", []):
        origin = embed.get("origin") if isinstance(embed, dict) else None
        if origin:
            origin = _safe_source(origin)
            if origin not in frame_src:
                frame_src.append(origin)

    def directive(name, values):
        return f"{name} {' '.join(values)}" if values else f"{name} 'none'"

    # The security boundary that matters for a page is connect-src — where it may
    # send data. A feature widens it to its resolved service origin; 'self' is always
    # present so the grove's own runtime can fetch manifest.json, blobs/, and the
    # search index from the page origin. (Once connect-src is named, default-src no
    # longer covers connections, so omitting 'self' would break the grove itself.)
    #
    # The grove shell renders first-party inline <style> (theme tokens) and inline
    # <script> (app boot, SW registration, theme init) that aren't individually
    # hashable here — allow inline for those. This matches the grove's posture on
    # non-chat pages (which carry no CSP at all); the egress scoping above is the win.
    parts = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        directive("connect-src", ["'self'", *connect]),
        directive("form-action", ["'self'", *form_action]),
        directive("frame-src", frame_src),
    ]
    return "; ".join(parts)
