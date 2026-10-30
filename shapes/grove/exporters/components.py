"""Grove build-time components — header, footer, card HTML generators."""
from datetime import datetime
from xml.sax.saxutils import escape

from icons import load_icon


def format_date(date_str: str, fmt: str | None = None) -> str:
    """Format ISO date (YYYY-MM-DD) using strftime fmt. Default: ISO passthrough.

    Throws on malformed input when a custom fmt is set — no silent fallback.
    """
    if not date_str:
        return ""
    if not fmt or fmt == "%Y-%m-%d":
        return date_str
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime(fmt)


def _render_action(action: dict, base_path: str, icons_dir) -> str:
    """Render a single header action based on feature or href."""
    label = escape(action["label"])
    style = escape(action.get("style", "ghost"))
    cls = f"btn btn-{style} btn-sm"

    icon_html = ""
    icon_id = action.get("icon")
    if icon_id:
        icon_html = load_icon(icon_id, icons_dir) + "\n            "

    feature = action.get("feature")
    href = action.get("href")

    if action.get("capability") is not None:
        raise ValueError(
            f"Header action '{label}' uses 'capability:' — renamed to 'feature:' "
            "(capability now names the machine binding table, not a grove feature)")

    if feature == "archive":
        url = f"{base_path}/archive/"
        return f'<a href="{url}" class="{cls}" aria-label="{label}">{label}</a>'

    if feature == "search":
        return (
            f'<button class="{cls}" data-action="open-search" '
            f'data-interaction="press" aria-label="{label}" type="button">\n'
            f'            {icon_html}'
            f'<span class="btn-label">{label}</span>\n'
            f'        </button>'
        )

    if href:
        # A root-relative href is relative to the grove root, so carry base_path —
        # like the archive feature above. (rstrip avoids // when base_path is "/".)
        # An absolute URL (scheme://…) is left untouched.
        if href.startswith("/"):
            href = f"{base_path.rstrip('/')}{href}"
        return f'<a href="{escape(href)}" class="{cls}" data-external>{label}</a>'

    raise ValueError(f"Header action '{label}' has neither feature nor href")


def _brand_inner(grove: dict, base_path: str) -> str:
    """The brand's inner markup: the logo image when grove.logo is set, else the
    title text. One source of truth for the header and the app-rail brands."""
    title = escape(grove["title"])
    logo = grove.get("logo")
    if logo:
        return f'<img src="{base_path}/{escape(logo)}" alt="{title}" class="site-logo" width="400" height="126">'
    return title


def render_header(grove: dict, ctx: dict) -> str:
    """Site header with declared actions from grove.yaml. A grove with no `header`
    block declares no header — render nothing (chromeless), not a crash. A header
    that IS declared must be well-formed (no fallback for a malformed one)."""
    if "header" not in grove:
        return ""
    base_path = ctx["base_path"]
    icons_dir = ctx["icons_dir"]
    home = f"{base_path}/"
    actions = grove["header"]["actions"]
    brand_html = _brand_inner(grove, base_path)

    actions_html = "\n        ".join(
        _render_action(a, base_path, icons_dir) for a in actions
    )

    return f"""<header class="site-header" role="banner">
    <a href="{home}" class="site-title">{brand_html}</a>
    <div class="header-actions">
        {actions_html}
    </div>
</header>"""


def _theme_toggle_button(strings: dict) -> str:
    """Theme-toggle button — shared by footer and app rail."""
    toggle_theme_label = escape(strings["toggle_theme"])
    return (
        f'<button class="btn btn-ghost btn-sm btn-icon btn-theme" data-action="toggle-theme" data-interaction="press" aria-label="{toggle_theme_label}" type="button">\n'
        f'            <span class="btn-state-light"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg></span>\n'
        f'            <span class="btn-state-dark"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg></span>\n'
        f'        </button>'
    )


def _clear_site_button(strings: dict, on_clear: str) -> str:
    """Clear-site button — shared by footer and app rail."""
    clear_site_label = escape(strings["clear_site"])
    on_clear_escaped = escape(on_clear)
    return (
        f'<button class="btn btn-ghost btn-sm btn-icon" data-action="clear-site" data-on-clear="{on_clear_escaped}" aria-label="{clear_site_label}" type="button">\n'
        f'            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>\n'
        f'        </button>'
    )


def render_footer(grove: dict, ctx: dict) -> str:
    """Site footer with RSS link and grove identity."""
    title = escape(grove["title"])
    base_url = ctx["base_url"].rstrip("/")
    rss_enabled = grove["rss"]["enabled"]
    strings = ctx["strings"]
    on_clear = ctx["on_clear"]

    rss_html = ""
    if rss_enabled:
        rss_html = f'\n        <a href="{base_url}/feed.xml">RSS</a>'

    return f"""<footer class="site-footer" role="contentinfo">
    <div class="footer-inner">
        <span>{title}</span>{rss_html}
        {_theme_toggle_button(strings)}
        {_clear_site_button(strings, on_clear)}
        <span class="build-id">__BUILD_HASH__</span>
    </div>
</footer>"""


def render_app_rail(grove: dict, ctx: dict) -> str:
    """Left rail for layout: app — the chat surface's chrome. Two zones: the brand
    (→ feed home) at the top, and a slot the chat mounts its conversation list into.
    NO site navigation here: nav belongs in the site header or nowhere — never split
    across the header AND the chat sidebar (that changes where the user expects it).
    The brand is the way back to the site, where the header carries the nav."""
    title = escape(grove["title"])
    base_path = ctx["base_path"]
    home = f"{base_path}/"
    brand_inner = _brand_inner(grove, base_path)
    return f"""<nav class="chat-rail" aria-label="{title}">
    <a href="{home}" class="chat-rail-brand site-title">{brand_inner}</a>
    <div class="chat-rail-conversations" data-chat-sidebar-slot></div>
</nav>"""


def render_card(post: dict, index: int = 0, base_path: str = "") -> str:
    """Post card for feed grid. index drives stagger animation."""
    title = escape(post["title"])
    url = escape(base_path + post["url_path"])
    date_iso = escape(str(post["publish_date"]))
    date_display = escape(str(post["publish_date_display"]))
    excerpt = escape(post["excerpt"])

    # Cap stagger index at 8 — beyond that, all cards appear together
    stagger_index = min(index, 8)

    # Card appearance overrides (bg, color) → CSS custom property overrides
    card_cfg = post.get("card") or {}
    style_parts = [f"--stagger-index: {stagger_index}"]
    if card_cfg.get("bg"):
        style_parts.append(f"--color-card-bg-resolved: {escape(card_cfg['bg'])}")
    if card_cfg.get("color"):
        style_parts.append(f"--color-text-resolved: {escape(card_cfg['color'])}")
        style_parts.append(f"--color-text-secondary-resolved: {escape(card_cfg['color'])}")
    if card_cfg.get("hover"):
        style_parts.append(f"--color-accent-resolved: {escape(card_cfg['hover'])}")
    style_attr = "; ".join(style_parts)

    # Thumbnail
    thumbnail = post.get("_thumbnail", "")
    thumb_html = ""
    if thumbnail:
        thumb_src = escape(base_path + "/" + thumbnail.lstrip("/"))
        thumb_html = f'\n    <img class="card-thumbnail" src="{thumb_src}" alt="" loading="lazy">'

    # Tags
    tags = post.get("tags") or []
    tags_html = ""
    if tags:
        pills = "".join(f'<span class="card-tag">{escape(t)}</span>' for t in tags)
        tags_html = f'\n        <div class="card-tags">{pills}</div>'

    return f"""<article class="card" data-stagger style="{style_attr}">{thumb_html}
    <div class="card-body">
        <a href="{url}" class="card-link">
            <time datetime="{date_iso}">{date_display}</time>
            <h2 class="card-title">{title}</h2>
            <p class="card-excerpt">{excerpt}</p>
        </a>{tags_html}
    </div>
</article>"""
