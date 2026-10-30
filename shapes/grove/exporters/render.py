"""Grove HTML renderer — markdown to HTML with OG tags and layout attributes."""
import json
import re
from xml.sax.saxutils import escape
from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound
from layouts import get_layout
from toc import extract_toc
from components import render_header, render_footer, render_card, format_date

# Pygments CSS class prefix — matches formatter output.
_PYGMENTS_CSSCLASS = "highlight"


def _highlight(code: str, lang: str, _attrs: str) -> str:
    """markdown-it highlight callback. Returns full <pre><code> block so
    markdown-it skips its default wrapping (triggered by startswith('<pre')).
    Unknown languages → empty string to fall back to the default renderer."""
    if not lang:
        return ""
    try:
        lexer = get_lexer_by_name(lang, stripnl=False)
    except ClassNotFound:
        return ""
    formatter = HtmlFormatter(nowrap=True)
    inner = highlight(code, lexer, formatter).rstrip("\n")
    lang_attr = escape(lang)
    return (
        f'<pre class="{_PYGMENTS_CSSCLASS}" data-lang="{lang_attr}">'
        f'<code class="language-{lang_attr}">{inner}</code></pre>'
    )


_MAIN_RE = re.compile(r'(<main\b[^>]*>)(.*?)(</main>)', re.DOTALL)


def _encrypt_page_html(html: str, encryptor, title: str) -> str:
    """Replace <main> content with encrypted envelope + gate container."""
    match = _MAIN_RE.search(html)
    if not match:
        raise ValueError("No <main> tag found in rendered HTML — cannot encrypt")

    main_open = match.group(1)
    main_content = match.group(2)
    main_close = match.group(3)

    meta = {"title": title}
    envelope_json = encryptor(main_content, meta)

    replacement = (
        f'{main_open}\n'
        f'        <div id="grove-gate"></div>\n'
        f'        <script type="application/json" id="grove-envelope">{envelope_json}</script>\n'
        f'    {main_close}'
    )
    return html[:match.start()] + replacement + html[match.end():]


_BG_RULE_RE = re.compile(r"background(?:-color)?\s*:\s*[^;}]+;?")


def _strip_bg_rules(css: str) -> str:
    """Remove `background` + `background-color` declarations from Pygments
    output so the token-driven `--color-code-bg-resolved` wins. Pygments'
    theme backgrounds (and hll highlight backgrounds) otherwise override it.
    """
    return _BG_RULE_RE.sub("", css)


def render_syntax_css() -> str:
    """Pygments stylesheet. Light palette at :root, dark at [data-theme='dark']."""
    light = HtmlFormatter(style="default").get_style_defs(f".{_PYGMENTS_CSSCLASS}")
    dark = HtmlFormatter(style="monokai").get_style_defs(
        f'[data-theme="dark"] .{_PYGMENTS_CSSCLASS}'
    )
    return f"{_strip_bg_rules(light)}\n\n{_strip_bg_rules(dark)}\n"


# html=True — allow inline HTML (figures, SVGs, captions) in markdown
# highlight callback → Pygments syntax colors written to dist/syntax.css at build.
_md = MarkdownIt("commonmark", {"html": True, "highlight": _highlight}).enable("table")


def _table_open(self, tokens, idx, options, env):
    return '<div class="table-wrap">' + self.renderToken(tokens, idx, options, env)


def _table_close(self, tokens, idx, options, env):
    return self.renderToken(tokens, idx, options, env) + "</div>\n"


_md.add_render_rule("table_open", _table_open)
_md.add_render_rule("table_close", _table_close)


def _resolve_og_image(image_path: str, manifest: dict | None, base_url: str) -> str:
    """Resolve OG image to absolute URL, preferring manifest og_safe entry."""
    if image_path.startswith("http://") or image_path.startswith("https://"):
        return image_path

    if manifest and image_path in manifest:
        entry = manifest[image_path]
        og_path = entry["original"]["path"]
        return f"{base_url}/{og_path.lstrip('/')}"

    # Not in manifest — log warning for internal paths
    if not image_path.startswith("http"):
        print(f'build warn: og.image "{image_path}" not found in image manifest')

    return f"{base_url}/{image_path.lstrip('/')}"


def _og_tags(post: dict, grove: dict, ctx: dict, page_url: str = "", manifest: dict | None = None) -> str:
    """Resolve OG meta tags. Grove declares the base; post layers on top.

    page_url — path portion of the canonical URL (e.g. "/posts/welcome/").
    Image paths stay relative in grove.yaml / frontmatter; resolved to
    absolute URLs here via base_url.
    """
    og = {**grove["og"], **{k: v for k, v in (post.get("og") or {}).items() if v is not None and v != ""}}

    base_url = ctx["base_url"].rstrip("/")

    parts = []
    for key in ("title", "description", "image"):
        value = og.get(key)
        if value:
            rendered = str(value)
            if key == "image":
                rendered = _resolve_og_image(rendered, manifest, base_url)
            parts.append(f'<meta property="og:{escape(key)}" content="{escape(rendered)}">')

    if page_url:
        canonical = f"{base_url}{page_url}"
        parts.append(f'<meta property="og:url" content="{escape(canonical)}">')

    og_type = "article" if post.get("title") else "website"
    parts.append(f'<meta property="og:type" content="{og_type}">')

    twitter_card = og.get("twitter_card")
    if twitter_card:
        parts.append(f'<meta name="twitter:card" content="{escape(twitter_card)}">')

    return "\n    ".join(parts)


def _page_shell(title: str, og: str, grove: dict, ctx: dict, layout: str, content: str,
                extra_body: str = "", *, chrome: bool = True, width: str = "content") -> str:
    """Shared HTML shell with header, footer, skip link.

    grove  — user-authored config from grove.yaml (read-only).
    ctx    — build-derived context: base_url, base_path, theme_css.
    chrome — when False, header and footer are omitted (composed pages own their chrome).
    """
    lang = escape(grove["lang"])
    base_url = ctx["base_url"].rstrip("/")
    base_path = ctx["base_path"]  # "" for root deploy, "/grove" for subpath
    theme_css = ctx["theme_css"]  # inline pre-paint tokens, no FOUC
    fonts_css = ctx.get("fonts_css", "")
    strings = ctx.get("strings", {})
    skip_text = escape(strings.get("skip_to_content", "Skip to content"))
    strings_json = json.dumps(strings, ensure_ascii=False)
    strings_script = f'\n    <script type="application/json" id="strings-data">{strings_json}</script>'
    header = render_header(grove, ctx) if chrome else ""
    footer = render_footer(grove, ctx) if chrome else ""

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
    <style id="grove-tokens">
{fonts_css}{theme_css}
    </style>
    <link rel="stylesheet" href="{base_path}/style.css">
    <link rel="stylesheet" href="{base_path}/elements.css">
    <link rel="stylesheet" href="{base_path}/transitions.css">
    <link rel="stylesheet" href="{base_path}/syntax.css">
    <link rel="modulepreload" href="{base_path}/shell-web/transport.js">
    <link rel="modulepreload" href="{base_path}/components/gate.js">
    <script>
      (function() {{
        var stored = localStorage.getItem('grove-theme');
        var theme = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        document.documentElement.setAttribute('data-theme', theme);
        var nav = performance.getEntriesByType('navigation')[0];
        if (!nav || nav.type !== 'back_forward') {{
          document.documentElement.classList.add('animate-entrance');
        }}
      }})();
      // Dev self-heal: if a service worker was registered on a previous visit,
      // its cache-first strategy will pin old CSS/JS forever. On localhost we
      // unregister it and purge caches, then reload once. Guarded by the
      // registration check so there's no reload loop after the SW is gone.
      (function() {{
        if (!(location.hostname === 'localhost' || location.hostname === '127.0.0.1')) return;
        if (!('serviceWorker' in navigator)) return;
        navigator.serviceWorker.getRegistrations().then(function(regs) {{
          if (regs.length === 0) return;
          Promise.all(regs.map(function(r) {{ return r.unregister(); }})).then(function() {{
            if ('caches' in self) {{
              caches.keys().then(function(keys) {{
                Promise.all(keys.map(function(k) {{ return caches.delete(k); }})).then(function() {{
                  location.reload();
                }});
              }});
            }} else {{
              location.reload();
            }}
          }});
        }});
      }})();
    </script>
</head>
<body data-layout="{escape(layout)}" data-width="{escape(width)}">
    <a class="skip-link" href="#main">{skip_text}</a>
    {header}
    <main id="main">
        {content}
    </main>
    {footer}{extra_body}{strings_script}
    <script type="module" src="{base_path}/app.js"></script>
</body>
</html>"""


def _strip_duplicate_h1(body: str, title: str) -> str:
    """Remove leading `# Title` from markdown body when it matches frontmatter title.
    Prevents title duplication: frontmatter owns the H1 (rendered in layout hero)."""
    stripped = body.lstrip()
    marker = f"# {title.strip()}"
    if stripped.startswith(marker):
        rest = stripped[len(marker):]
        # require a newline or EOF after the title — avoid matching `# Title something`
        if rest[:1] in ("", "\n", "\r"):
            return rest.lstrip("\n\r")
    return body


def render_post(post: dict, grove: dict, ctx: dict, *, encryptor=None, manifest=None) -> str:
    """Full HTML page for a single post. ctx carries base_url/base_path/theme_css."""
    layout_name = post.get("layout")  # optional per-post override
    if not layout_name:
        layout_name = grove["defaults"]["layout"]  # required in grove.yaml

    title = escape(post["title"])
    og = _og_tags(post, grove, ctx, page_url=post["url_path"], manifest=manifest)
    body = _strip_duplicate_h1(post["body"], post["title"])
    body_html = _md.render(body)

    # Image post-processing — transform <img> to <picture> using manifest
    if manifest:
        from image_tags import transform_images
        body_html = transform_images(body_html, manifest, base_path=ctx["base_path"])

    # Pre-format date for hero display — layouts read publish_date_display
    date_fmt = grove.get("date_format")
    date_display = format_date(str(post.get("publish_date") or ""), date_fmt)

    # Build post dict with rendered HTML for layout function
    post_with_html = {**post, "body_html": body_html, "publish_date_display": date_display}
    layout_fn = get_layout(layout_name)
    layout_html = layout_fn(post_with_html)

    # Extract TOC and inject as JSON for article layout
    extra_body = ""
    if layout_name == "article":
        toc_entries = extract_toc(body_html)
        if toc_entries:
            toc_json = json.dumps(toc_entries)
            extra_body = f'\n    <script type="application/json" id="toc-data">{toc_json}</script>'

    html = _page_shell(title, og, grove, ctx, layout_name, layout_html, extra_body=extra_body)

    if encryptor:
        html = _encrypt_page_html(html, encryptor, post["title"])

    return html


def render_post_fragment(post: dict, grove: dict, ctx: dict, *, manifest=None) -> str:
    """Content that goes inside <main> for a single post. No page shell."""
    layout_name = post.get("layout")
    if not layout_name:
        layout_name = grove["defaults"]["layout"]

    body = _strip_duplicate_h1(post["body"], post["title"])
    body_html = _md.render(body)

    if manifest:
        from image_tags import transform_images
        body_html = transform_images(body_html, manifest, base_path=ctx["base_path"])

    date_fmt = grove.get("date_format")
    date_display = format_date(str(post.get("publish_date") or ""), date_fmt)

    post_with_html = {**post, "body_html": body_html, "publish_date_display": date_display}
    layout_fn = get_layout(layout_name)
    layout_html = layout_fn(post_with_html)

    extra_body = ""
    if layout_name == "article":
        toc_entries = extract_toc(body_html)
        if toc_entries:
            toc_json = json.dumps(toc_entries)
            extra_body = f'\n    <script type="application/json" id="toc-data">{toc_json}</script>'

    return layout_html + extra_body


def render_archive_page(posts: list[dict], grove: dict, ctx: dict, *, manifest=None) -> str:
    """Archive page grouping all posts by year."""
    strings = ctx.get("strings", {})
    archive_label = escape(strings.get("archive_title", "Archive"))
    title = f"{archive_label} — {escape(grove['title'])}"
    og = _og_tags({}, grove, ctx, page_url="/archive/", manifest=manifest)
    date_fmt = grove.get("date_format")

    # Group posts by year
    years: dict[str, list] = {}
    for post in posts:
        date_str = str(post["publish_date"]) if "publish_date" in post else ""
        year = date_str[:4] if date_str else "undated"
        years.setdefault(year, []).append(post)

    base_path = ctx["base_path"]
    sections = []
    for year in sorted(years.keys(), reverse=True):
        items = []
        for post in years[year]:
            post_title = escape(post["title"])
            url = escape(base_path + post["url_path"])
            date_iso = str(post["publish_date"]) if "publish_date" in post else ""
            date_display = format_date(date_iso, date_fmt)
            date_iso_escaped = escape(date_iso)
            date_display_escaped = escape(date_display)
            items.append(f'            <li><time datetime="{date_iso_escaped}">{date_display_escaped}</time> <a href="{url}">{post_title}</a></li>')
        items_html = "\n".join(items)
        sections.append(f"""        <section>
            <h2>{escape(year)}</h2>
            <ul>
{items_html}
            </ul>
        </section>""")

    sections_html = "\n".join(sections)
    content = f"""<h1>{archive_label}</h1>
{sections_html}"""

    return _page_shell(title, og, grove, ctx, "archive", content)


def render_archive_fragment(posts: list[dict], grove: dict, ctx: dict) -> str:
    """Content that goes inside <main> for the archive page. No page shell."""
    strings = ctx.get("strings", {})
    archive_label = escape(strings.get("archive_title", "Archive"))
    date_fmt = grove.get("date_format")

    years: dict[str, list] = {}
    for post in posts:
        date_str = str(post["publish_date"]) if "publish_date" in post else ""
        year = date_str[:4] if date_str else "undated"
        years.setdefault(year, []).append(post)

    base_path = ctx["base_path"]
    sections = []
    for year in sorted(years.keys(), reverse=True):
        items = []
        for post in years[year]:
            post_title = escape(post["title"])
            url = escape(base_path + post["url_path"])
            date_iso = str(post["publish_date"]) if "publish_date" in post else ""
            date_display = format_date(date_iso, date_fmt)
            date_iso_escaped = escape(date_iso)
            date_display_escaped = escape(date_display)
            items.append(f'            <li><time datetime="{date_iso_escaped}">{date_display_escaped}</time> <a href="{url}">{post_title}</a></li>')
        items_html = "\n".join(items)
        sections.append(f"""        <section>
            <h2>{escape(year)}</h2>
            <ul>
{items_html}
            </ul>
        </section>""")

    sections_html = "\n".join(sections)
    return f"""<h1>{archive_label}</h1>
{sections_html}"""


def render_index_page(posts: list[dict], grove: dict, ctx: dict, page_title: str = "", *, manifest=None) -> str:
    """Index/listing page with post cards in a feed grid."""
    title = escape(page_title) if page_title else escape(grove["title"])
    og = _og_tags({}, grove, ctx, page_url="/", manifest=manifest)
    date_fmt = grove.get("date_format")

    # Enrich posts with formatted date and card thumbnail (post-level only, no grove fallback)
    enriched = [
        {
            **p,
            "publish_date_display": format_date(str(p.get("publish_date") or ""), date_fmt),
            "_thumbnail": (p.get("card") or {}).get("image", ""),
        }
        for p in posts
    ]

    base_path = ctx["base_path"]
    cards = "\n".join(
        f"        {render_card(post, index=i, base_path=base_path)}" for i, post in enumerate(enriched)
    )
    content = f'<div class="feed-grid">\n{cards}\n        </div>'
    return _page_shell(title, og, grove, ctx, "index", content)


def render_index_fragment(posts: list[dict], grove: dict, ctx: dict, page_title: str = "", *, manifest=None) -> str:
    """Content that goes inside <main> for the index/listing page. No page shell."""
    date_fmt = grove.get("date_format")

    # Enrich posts with formatted date and card thumbnail (post-level only, no grove fallback)
    enriched = [
        {
            **p,
            "publish_date_display": format_date(str(p.get("publish_date") or ""), date_fmt),
            "_thumbnail": (p.get("card") or {}).get("image", ""),
        }
        for p in posts
    ]

    base_path = ctx["base_path"]
    cards = "\n".join(
        f"        {render_card(post, index=i, base_path=base_path)}" for i, post in enumerate(enriched)
    )
    return f'<div class="feed-grid">\n{cards}\n        </div>'


def render_gate_page(grove: dict, ctx: dict) -> str:
    """Gate page for whole-grove encryption.

    Includes header/footer (hidden by gate layout CSS). After unlock,
    app.js changes data-layout and they appear. No content leak —
    header/footer are site chrome, not post content.
    """
    lang = escape(grove["lang"])
    base_path = ctx["base_path"]
    theme_css = ctx["theme_css"]
    fonts_css = ctx.get("fonts_css", "")
    strings = ctx.get("strings", {})
    skip_text = escape(strings.get("skip_to_content", "Skip to content"))
    strings_json = json.dumps(strings, ensure_ascii=False)
    strings_script = f'\n    <script type="application/json" id="strings-data">{strings_json}</script>'
    site_title = escape(grove["title"])
    header = render_header(grove, ctx)
    footer = render_footer(grove, ctx)

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="grove-base-path" content="{escape(base_path)}">
    <meta name="grove-encrypted" content="bundle">
    <title>{site_title}</title>
    <link rel="icon" href="{base_path}/theme/favicon.svg" type="image/svg+xml">
    <link rel="icon" href="{base_path}/theme/favicon.ico" sizes="32x32">
    <link rel="apple-touch-icon" href="{base_path}/theme/apple-touch-icon.png">
    <style id="grove-tokens">
{fonts_css}{theme_css}
    </style>
    <link rel="stylesheet" href="{base_path}/style.css">
    <link rel="stylesheet" href="{base_path}/elements.css">
    <link rel="stylesheet" href="{base_path}/transitions.css">
    <link rel="stylesheet" href="{base_path}/syntax.css">
    <link rel="modulepreload" href="{base_path}/shell-web/transport.js">
    <link rel="modulepreload" href="{base_path}/components/gate.js">
    <script>
      (function() {{
        var stored = localStorage.getItem('grove-theme');
        var theme = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        document.documentElement.setAttribute('data-theme', theme);
        var nav = performance.getEntriesByType('navigation')[0];
        if (!nav || nav.type !== 'back_forward') {{
          document.documentElement.classList.add('animate-entrance');
        }}
      }})();
    </script>
</head>
<body data-layout="gate">
    <a class="skip-link" href="#main">{skip_text}</a>
    {header}
    <main id="main">
        <div id="grove-gate"></div>
    </main>
    {footer}{strings_script}
    <script type="module" src="{base_path}/app.js"></script>
</body>
</html>"""
