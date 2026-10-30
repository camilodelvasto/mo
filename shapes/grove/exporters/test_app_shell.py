"""Tests for app shell (index.html) generation."""
from pathlib import Path
from app_shell import render_app_shell


def _grove():
    return {
        "title": "Test Grove", "lang": "en",
        "og": {"title": "Test", "description": "A test.", "image": "og.png"},
        "defaults": {"layout": "article", "view": "grid", "posts_per_page": 12},
        "rss": {"enabled": True, "max_items": 20},
        "header": {
            "actions": [
                {"label": "Archive", "feature": "archive", "style": "ghost"},
                {"label": "Search", "feature": "search", "style": "accent", "icon": "search"},
            ]
        },
    }


def _ctx():
    icons_dir = Path(__file__).resolve().parent.parent / "icons"
    return {"base_url": "https://moui.io", "base_path": "", "theme_css": ":root { --x: 1; }",
            "on_clear": "reload", "icons_dir": icons_dir,
            "strings": {"toggle_theme": "Toggle theme", "clear_site": "Clear site data",
                        "skip_to_content": "Skip to content"}}


def test_shell_is_valid_html():
    html = render_app_shell(_grove(), _ctx())
    assert "<!DOCTYPE html>" in html
    assert "</html>" in html

def test_shell_has_header():
    html = render_app_shell(_grove(), _ctx())
    assert "site-header" in html

def test_shell_has_footer():
    html = render_app_shell(_grove(), _ctx())
    assert "site-footer" in html
    assert "build-id" in html

def test_shell_has_empty_main_without_skeletons():
    html = render_app_shell(_grove(), _ctx())
    assert '<main id="main"></main>' in html

def test_shell_has_skeleton_cards():
    html = render_app_shell(_grove(), _ctx(), skeleton_count=3)
    assert 'card-skeleton' in html
    assert html.count('card-skeleton') == 3
    assert 'feed-grid' in html
    assert 'skeleton-image' in html
    assert 'card-body' in html
    assert '<main id="main"></main>' not in html

def test_shell_skeleton_count_zero():
    html = render_app_shell(_grove(), _ctx(), skeleton_count=0)
    assert '<main id="main"></main>' in html
    assert 'card-skeleton' not in html

def test_shell_has_theme_init_script():
    html = render_app_shell(_grove(), _ctx())
    assert "grove-theme" in html
    assert "data-theme" in html

def test_shell_has_no_sw_self_heal():
    html = render_app_shell(_grove(), _ctx())
    assert "serviceWorker" not in html

def test_shell_has_og_tags():
    html = render_app_shell(_grove(), _ctx())
    assert 'og:title' in html

def test_shell_has_base_path_meta():
    ctx = {**_ctx(), "base_path": "/grove"}
    html = render_app_shell(_grove(), ctx)
    assert 'grove-base-path" content="/grove"' in html

def test_shell_has_theme_css():
    html = render_app_shell(_grove(), _ctx())
    assert "--x: 1" in html

def test_shell_has_build_hash_in_footer():
    html = render_app_shell(_grove(), _ctx())
    assert "__BUILD_HASH__" in html
    assert '<p class="build-hash">' not in html

def test_shell_links_app_js():
    html = render_app_shell(_grove(), _ctx())
    assert 'app.js' in html

def test_shell_has_data_layout_index():
    html = render_app_shell(_grove(), _ctx())
    assert 'data-layout="index"' in html
