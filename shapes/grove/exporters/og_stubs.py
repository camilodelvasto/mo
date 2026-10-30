"""OG page generation — full app shells with per-post OG tags at canonical paths.

Each page is a complete app shell (header, footer, theme, app.js) with per-post
OG meta tags in <head>. Crawlers read OG tags and stop. Humans get the app boot
(reads pathname, navigates to the route). No meta-refresh, no redirect.

Written at canonical paths: dist/architecture/corpus-format/index.html.
"""
from pathlib import Path
from app_shell import render_app_shell


def write_og_stubs(entries: list[dict], dist: Path, *, base_url: str,
                   grove: dict, ctx: dict) -> None:
    """Write per-post app shells with OG tags at canonical paths.

    Skips index and archive routes — index is the root app shell,
    archive is navigated from within the app.
    """
    skip_types = {"index", "archive"}
    for entry in entries:
        if entry.get("type") in skip_types:
            continue
        route = entry["route"]
        og = entry.get("og", {})
        if not og.get("title"):
            continue

        og_override = {
            "title": og.get("title", ""),
            "description": og.get("description", ""),
            "image": og.get("image", ""),
            "url": f"{base_url.rstrip('/')}/{route.lstrip('/')}",
            "type": "article",
        }

        shell_html = render_app_shell(
            grove, ctx,
            og_override=og_override,
            title_override=og.get("title", ""),
        )

        stub_path = dist / route.strip("/") / "index.html"
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_path.write_text(shell_html, encoding="utf-8")


def write_full_stubs(entries: list[dict], pages: dict[str, str],
                     dist: Path, *, base_url: str,
                     grove: dict, ctx: dict,
                     chat_config: dict | None = None,
                     feature_endpoints: dict | None = None) -> None:
    """Write app shells with pre-rendered content at canonical paths.

    SSG-with-hydration: crawlers see full article content, humans get the
    app shell boot. content_override pre-populates <main> so the page is
    visible before JS loads.

    Skips index and archive routes — index is the root app shell,
    archive is navigated from within the app.
    """
    skip_types = {"index", "archive"}
    for entry in entries:
        if entry.get("type") in skip_types:
            continue
        route = entry["route"]
        og = entry.get("og", {})
        if not og.get("title"):
            continue
        content = pages.get(route, "")

        og_override = {
            "title": og.get("title", ""),
            "description": og.get("description", ""),
            "image": og.get("image", ""),
            "url": f"{base_url.rstrip('/')}/{route.lstrip('/')}",
            "type": "article",
        }

        shell_html = render_app_shell(
            grove, ctx,
            og_override=og_override,
            title_override=og.get("title", ""),
            content_override=content,
            chat_config=chat_config,
            feature_endpoints=feature_endpoints,
        )

        stub_path = dist / route.strip("/") / "index.html"
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_path.write_text(shell_html, encoding="utf-8")
