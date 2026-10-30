"""Tests for grove built-in elements."""
from pathlib import Path
from builtins_grove import BUILTINS, is_builtin


def _grove():
    return {
        "id": "g",
        "title": "Test Grove",
        "lang": "en",
        "og": {"title": "T", "description": "d", "image": "og.png"},
        "rss": {"enabled": False},
        "header": {
            "actions": [
                {"label": "Archive", "feature": "archive", "style": "ghost"},
            ]
        },
    }


def _ctx():
    icons_dir = Path(__file__).resolve().parent.parent / "icons"
    return {
        "base_url": "https://e.com",
        "base_path": "",
        "strings": {
            "toggle_theme": "Toggle theme",
            "clear_site": "Clear site data",
        },
        "on_clear": "reload",
        "icons_dir": icons_dir,
    }


def test_registry_content_builtins_only():
    # grid is the content built-in; header/footer are chrome — owned by the shell, not body
    assert is_builtin("grid")
    assert not is_builtin("header")
    assert not is_builtin("footer")
    assert not is_builtin("nope")


def test_grid_renders_cards_for_posts():
    posts = [{"title": "P1", "url_path": "/p1/", "excerpt": "x", "publish_date": "2026-01-01",
              "content_path": "p1", "card": {}}]
    html = BUILTINS["grid"]({"collection": "posts", "limit": 12}, _grove(), _ctx(), posts=posts)
    assert "P1" in html
    assert 'class="feed-grid"' in html


def _make_post(title):
    return {"title": title, "url_path": f"/{title.lower()}/", "excerpt": "x",
            "publish_date": "2026-01-01", "content_path": title.lower(), "card": {}}


def test_grid_respects_limit():
    posts = [_make_post("P1"), _make_post("P2"), _make_post("P3")]
    html = BUILTINS["grid"]({"limit": 2}, _grove(), _ctx(), posts=posts)
    assert "P1" in html
    assert "P2" in html
    assert "P3" not in html


