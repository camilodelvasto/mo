"""Grove layout templates. Post-level HTML shells.

Layouts control structure (what surrounds content), not styling (that's the theme).
Any layout composes with any theme.
"""
from xml.sax.saxutils import escape


def article_layout(post):
    """Default layout: hero header (title + date), body."""
    title = escape(post["title"])  # required — guaranteed by content.py
    body_html = post["body_html"]  # required — set by render.py

    date_iso = post.get("publish_date")  # ISO string, may be empty
    date_display = post.get("publish_date_display") or date_iso  # formatted, set by render.py
    date_html = ""
    if date_iso:
        date_html = f'<time datetime="{escape(str(date_iso))}">{escape(str(date_display))}</time>'

    return f"""<article class="article-layout">
    <header class="post-hero">
        <div class="post-hero-inner">
            <h1>{title}</h1>
            {date_html}
        </div>
    </header>
    <div class="post-body">
        {body_html}
    </div>
</article>"""


def quote_layout(post):
    """Quote layout: large typographic treatment, centered, minimal chrome.
    Content is markdown-body-driven — quote text + attribution in markdown."""
    body_html = post["body_html"]  # required — set by render.py

    return f"""<article class="quote-layout">
    <div class="post-body">
        {body_html}
    </div>
</article>"""


def landing_layout(post):
    """Landing layout: full-bleed sections, no standard article header."""
    body_html = post["body_html"]  # required — set by render.py

    return f"""<article class="landing-layout">
    <div class="post-body">
        {body_html}
    </div>
</article>"""


def minimal_layout(post):
    """Minimal layout: body only. No header, no tags, no related, no prev/next."""
    body_html = post["body_html"]  # required — set by render.py

    return f"""<article class="minimal-layout">
    <div class="post-body">
        {body_html}
    </div>
</article>"""


LAYOUTS = {
    "article": article_layout,
    "quote": quote_layout,
    "landing": landing_layout,
    "minimal": minimal_layout,
}


def get_layout(name):
    """Get layout function by name. Throws KeyError if not found."""
    if name not in LAYOUTS:
        raise KeyError(f"Unknown layout: '{name}'. Available: {', '.join(LAYOUTS.keys())}")
    return LAYOUTS[name]
