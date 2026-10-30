"""Page composer. Turns a page record into a fragment or a full page.

A body item is "self" (this page's index.html), a bare name ("grid"),
a single-key map with config ({grid: {limit: 12}}), or a feature ({feature: id}).
Composition only — no styling here. The per-page CSP is computed from declared
egress + features referenced in body.

Chrome model: the shell owns chrome (header/footer). By default composed pages
render with chrome=True. A page declares layout: landing, minimal, or app to
suppress chrome (full-bleed); app additionally owns the frame (rail + column).
"""
import base64
import hashlib
from xml.sax.saxutils import escape

from render import _page_shell, _og_tags
from elements import resolve_element
from csp import compute_csp
from components import render_app_rail
from chat_config import emit_chat_config


def _sha256_csp(script: str) -> str:
    """Return a CSP hash token for an inline script, e.g. 'sha256-abc…'."""
    digest = hashlib.sha256(script.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def _allowed_origins(csp_value: str) -> list[str]:
    origins = []
    for part in csp_value.split(";"):
        part = part.strip()
        if part.startswith(("connect-src", "frame-src", "form-action")):
            for tok in part.split()[1:]:
                if tok.startswith(("http://", "https://")):
                    origins.append(tok)
    return origins


def compose_fragment(page, grove, ctx, *, grove_root, posts, feature_endpoints):
    """Return (html, script_hashes) for a page's <main> inner HTML."""
    base_csp = compute_csp(page, grove, feature_endpoints=feature_endpoints)
    allowed = _allowed_origins(base_csp)
    parts, scripts = [], []
    for item in page["body"]:
        frag, script = resolve_element(item, grove, ctx, grove_root=grove_root,
                                       page_folder=page["folder"], page_route=page["route"],
                                       posts=posts, allowed_origins=allowed)
        parts.append(frag)
        if script:
            scripts.append(script)
    body_html = "\n".join(parts)
    # layout: app — the chat surface owns the frame. The rail (chrome) wraps the
    # composed body in a conversation column. Done HERE in the fragment (not only in
    # compose_page) so the dev server, which fills #main from compose_fragment, gets
    # the same frame as the static build. Header/footer suppression is CSS-driven
    # (body[data-layout="app"]) since the dev app shell always renders them.
    if (page.get("layout") or "page") == "app":
        rail = render_app_rail(grove, ctx)
        body_html = (f'<div class="app-shell">{rail}'
                     f'<div class="app-column">{body_html}</div></div>')
    return body_html, [_sha256_csp(s) for s in scripts]


def _page_has_chat_feature(page: dict, grove: dict) -> bool:
    """Return True if the page body mounts at least one feature whose type is chat."""
    chat_ids = {f.get("id") for f in grove.get("features", []) if f.get("type") == "chat"}
    for item in page.get("body", []):
        if isinstance(item, dict) and item.get("feature") in chat_ids:
            return True
    return False


def compose_page(page, grove, ctx, *, grove_root, posts, feature_endpoints,
                 chat_config=None, pages=None):
    content, script_hashes = compose_fragment(page, grove, ctx, grove_root=grove_root,
                                              posts=posts, feature_endpoints=feature_endpoints)
    csp = compute_csp(page, grove, feature_endpoints=feature_endpoints, script_hashes=script_hashes)
    title = escape(page["title"])
    og_input = {"title": page["title"], "og": page.get("og") or {}}
    og = _og_tags(og_input, grove, ctx, page_url=page["route"])
    csp_meta = f'<meta http-equiv="Content-Security-Policy" content="{escape(csp)}">'
    layout = page.get("layout") or "page"
    chrome = layout not in ("landing", "minimal", "app")
    # app owns the frame (content already wrapped in the rail by compose_fragment);
    # width is meaningless there, so force full. Otherwise width is orthogonal.
    width = "full" if layout == "app" else page.get("width", "content")
    html = _page_shell(title, og + "\n    " + csp_meta, grove, ctx, layout, content,
                       chrome=chrome, width=width)
    # Inject the chat-config island before </head> when this page mounts a chat feature,
    # mirroring the dev server's </head> replacement in server.py.
    if chat_config is not None and _page_has_chat_feature(page, grove):
        if pages is None:
            raise ValueError(
                "compose_page needs pages= when chat_config is set "
                "(the chat-config island maps ALL chat pages' routes)"
            )
        island = emit_chat_config(grove, pages, ctx,
                                  endpoint=chat_config["endpoint"],
                                  gate=chat_config.get("gate"))
        html = html.replace("</head>", island + "</head>", 1)
    return html
