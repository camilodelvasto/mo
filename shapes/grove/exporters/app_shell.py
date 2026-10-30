"""App shell renderer — the single index.html for the local-first grove.

Renders the permanent chrome: header, footer, theme CSS, theme init script,
app.js. <main> starts empty — populated by the router on navigation.

For the root index.html: grove-level OG tags, grove title.
For per-post app shells (at canonical paths): per-post OG tags, post title.
Both are full app shells — crawlers read OG tags, humans get the app boot.
No meta-refresh, no redirect. One file serves both purposes.
"""
import json
from html import escape

from components import render_header, render_footer


def _build_og_tags(*, title, description="", image="", url="",
                   og_type="website", twitter_card="", base_url=""):
    """Build OG meta tag string from explicit values."""
    parts = []
    if title:
        parts.append(f'<meta property="og:title" content="{escape(str(title))}">')
    if description:
        parts.append(f'<meta property="og:description" content="{escape(str(description))}">')
    if image:
        abs_image = image if image.startswith("http") else f"{base_url}/{image.lstrip('/')}"
        parts.append(f'<meta property="og:image" content="{escape(abs_image)}">')
    if url:
        parts.append(f'<meta property="og:url" content="{escape(str(url))}">')
    if og_type:
        parts.append(f'<meta property="og:type" content="{escape(str(og_type))}">')
    if twitter_card or image:
        card = twitter_card or ("summary_large_image" if image else "summary")
        parts.append(f'<meta name="twitter:card" content="{escape(str(card))}">')
    return "\n    ".join(parts)


def _render_skeleton_cards(count: int) -> str:
    """Render skeleton placeholder cards for the feed grid.

    Baked into the HTML so they're visible before JS loads.
    The router replaces them when real content is ready.
    """
    if count <= 0:
        return ""
    cards = []
    for i in range(count):
        stagger = min(i, 8)
        cards.append(
            f'<article class="card card-skeleton" style="--stagger-index: {stagger}">'
            '\n        <div class="skeleton-bar skeleton-image"></div>'
            '\n        <div class="card-body">'
            '\n            <div class="skeleton-bar skeleton-date"></div>'
            '\n            <div class="skeleton-bar skeleton-title"></div>'
            '\n            <div class="skeleton-bar skeleton-excerpt"></div>'
            '\n            <div class="skeleton-bar skeleton-excerpt skeleton-short"></div>'
            '\n        </div>'
            '\n    </article>'
        )
    return '<div class="feed-grid">\n    ' + '\n    '.join(cards) + '\n    </div>'


def render_app_shell(grove: dict, ctx: dict, *, og_override: dict | None = None,
                     title_override: str = "", skeleton_count: int = 0,
                     content_override: str = "",
                     chat_config: dict | None = None,
                     feature_endpoints: dict | None = None) -> str:
    """Render the app shell index.html.

    og_override: per-post OG dict with title, description, image, url.
                 If None, uses grove-level OG defaults.
    title_override: per-post <title>. If empty, uses grove title.
    skeleton_count: number of skeleton placeholder cards to render in <main>.
    chat_config: when present, emits the CSP meta + chat-config island in <head>.
    feature_endpoints: maps feature id → resolved service origin; required when chat_config is set.
    """
    lang = escape(grove["lang"])
    title = escape(title_override or grove["title"])
    base_url = ctx["base_url"].rstrip("/")
    base_path = ctx["base_path"]
    theme_css = ctx["theme_css"]
    fonts_css = ctx["fonts_css"]

    if og_override:
        og = _build_og_tags(
            title=og_override.get("title", ""),
            description=og_override.get("description", ""),
            image=og_override.get("image", ""),
            url=og_override.get("url", ""),
            og_type=og_override.get("type", "article"),
            twitter_card=grove.get("og", {}).get("twitter_card", ""),
            base_url=base_url,
        )
    else:
        grove_og = grove.get("og", {})
        og = _build_og_tags(
            title=grove_og.get("title", grove["title"]),
            description=grove_og.get("description", ""),
            image=grove_og.get("image", ""),
            url=f"{base_url}{base_path}/",
            og_type="website",
            twitter_card=grove_og.get("twitter_card", ""),
            base_url=base_url,
        )

    strings = ctx.get("strings", {})
    skip_text = escape(strings.get("skip_to_content", "Skip to content"))
    strings_json = json.dumps(strings, ensure_ascii=False)
    strings_script = f'\n    <script type="application/json" id="strings-data">{strings_json}</script>'

    header = render_header(grove, ctx)
    footer = render_footer(grove, ctx)

    fonts_block = f'    <style id="grove-fonts">\n{fonts_css}\n    </style>\n' if fonts_css else ""

    head_extra = ""
    if chat_config is not None:
        if feature_endpoints is None:
            raise ValueError(
                "render_app_shell: chat_config was provided but feature_endpoints is None — "
                "cannot build CSP connect-src without resolved feature endpoints"
            )
        from csp import compute_csp
        from chat_config import emit_chat_config
        from pages import load_pages
        feat_ids = [f["id"] for f in grove.get("features", []) if f.get("type") == "chat"]
        synthetic = {"body": [{"feature": fid} for fid in feat_ids], "egress": {}}
        csp = compute_csp(synthetic, grove, feature_endpoints=feature_endpoints)
        head_extra += f'    <meta http-equiv="Content-Security-Policy" content="{escape(csp, quote=False)}">\n'
        head_extra += emit_chat_config(grove, load_pages(ctx["_grove_root"], grove), ctx,
                                       endpoint=chat_config["endpoint"],
                                       gate=chat_config.get("gate"))

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="grove-base-path" content="{escape(base_path)}">
    <title>{title}</title>
    <link rel="icon" href="{base_path}/theme/favicon.svg" type="image/svg+xml">
    <link rel="icon" href="{base_path}/theme/favicon.ico" sizes="32x32">
    <link rel="apple-touch-icon" href="{base_path}/theme/apple-touch-icon.png">
    {og}
    <link rel="alternate" type="application/rss+xml" title="{escape(grove['title'])}" href="{base_url}/feed.xml">
{fonts_block}    <style id="grove-tokens">
{theme_css}
    </style>
    <style id="grove-chrome-suppress">
      /* The dev app shell renders header/footer for every route; the core sheet
         that hides them on chrome-less layouts loads via the async <link> below,
         so without this inline rule the chrome FOUC-flashes on first paint. */
      body[data-layout="app"] .site-header, body[data-layout="app"] .site-footer,
      body[data-layout="landing"] .site-header, body[data-layout="landing"] .site-footer,
      body[data-layout="minimal"] .site-header, body[data-layout="minimal"] .site-footer,
      body[data-layout="gate"] .site-header, body[data-layout="gate"] .site-footer {{ display: none; }}
    </style>
    <link rel="stylesheet" href="{base_path}/style.css">
    <link rel="stylesheet" href="{base_path}/elements.css">
    <link rel="stylesheet" href="{base_path}/transitions.css">
    <link rel="stylesheet" href="{base_path}/syntax.css">
    <script>
      (function() {{
        var stored = localStorage.getItem('grove-theme');
        var theme = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        document.documentElement.setAttribute('data-theme', theme);
      }})();
    </script>
{head_extra}</head>
<body data-layout="index">
    <a class="skip-link" href="#main">{skip_text}</a>
    {header}
    <main id="main">{content_override or _render_skeleton_cards(skeleton_count)}</main>
    {footer}{strings_script}
    <script type="module" src="{base_path}/app.js"></script>
</body>
</html>"""
