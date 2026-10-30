"""Tests for OG page generation — full app shells at canonical paths."""
from pathlib import Path
from og_stubs import write_og_stubs


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
            "on_clear": "reload", "crawlable": "thin", "icons_dir": icons_dir,
            "strings": {"toggle_theme": "Toggle theme", "clear_site": "Clear site data",
                        "skip_to_content": "Skip to content"}}


def _entries():
    return [
        {"route": "/welcome/", "type": "post",
         "og": {"title": "Welcome", "description": "Hi.", "image": ""}},
        {"route": "/arch/format/", "type": "post",
         "og": {"title": "Format", "description": "D.", "image": "assets/og.png"}},
    ]


def test_writes_files_at_canonical_paths(tmp_path):
    write_og_stubs(_entries(), tmp_path, base_url="https://moui.io",
                   grove=_grove(), ctx=_ctx())
    assert (tmp_path / "welcome" / "index.html").exists()
    assert (tmp_path / "arch" / "format" / "index.html").exists()


def test_has_per_post_og_title(tmp_path):
    write_og_stubs(_entries(), tmp_path, base_url="https://moui.io",
                   grove=_grove(), ctx=_ctx())
    html = (tmp_path / "welcome" / "index.html").read_text()
    assert 'og:title" content="Welcome"' in html


def test_has_per_post_og_description(tmp_path):
    write_og_stubs(_entries(), tmp_path, base_url="https://moui.io",
                   grove=_grove(), ctx=_ctx())
    html = (tmp_path / "welcome" / "index.html").read_text()
    assert 'og:description" content="Hi."' in html


def test_has_canonical_url(tmp_path):
    write_og_stubs(_entries(), tmp_path, base_url="https://moui.io",
                   grove=_grove(), ctx=_ctx())
    html = (tmp_path / "welcome" / "index.html").read_text()
    assert 'og:url" content="https://moui.io/welcome/"' in html


def test_has_og_image_when_present(tmp_path):
    write_og_stubs(_entries(), tmp_path, base_url="https://moui.io",
                   grove=_grove(), ctx=_ctx())
    html = (tmp_path / "arch" / "format" / "index.html").read_text()
    assert 'og:image" content="https://moui.io/assets/og.png"' in html


def test_is_full_app_shell(tmp_path):
    write_og_stubs(_entries(), tmp_path, base_url="https://moui.io",
                   grove=_grove(), ctx=_ctx())
    html = (tmp_path / "welcome" / "index.html").read_text()
    assert "<!DOCTYPE html>" in html
    assert "site-header" in html
    assert "site-footer" in html
    assert "app.js" in html
    assert '<main id="main"></main>' in html


def test_no_meta_refresh(tmp_path):
    write_og_stubs(_entries(), tmp_path, base_url="https://moui.io",
                   grove=_grove(), ctx=_ctx())
    html = (tmp_path / "welcome" / "index.html").read_text()
    assert "http-equiv" not in html
    assert "meta-refresh" not in html.lower()


def test_has_per_post_title_tag(tmp_path):
    write_og_stubs(_entries(), tmp_path, base_url="https://moui.io",
                   grove=_grove(), ctx=_ctx())
    html = (tmp_path / "welcome" / "index.html").read_text()
    assert "<title>Welcome</title>" in html


def test_skips_index_route(tmp_path):
    entries = [{"route": "/", "type": "index",
                "og": {"title": "Home", "description": "Home.", "image": ""}}]
    write_og_stubs(entries, tmp_path, base_url="https://moui.io",
                   grove=_grove(), ctx=_ctx())
    files = list(tmp_path.rglob("index.html"))
    assert len(files) == 0


def test_skips_archive(tmp_path):
    entries = [{"route": "/archive/", "type": "archive",
                "og": {"title": "Archive", "description": "All.", "image": ""}}]
    write_og_stubs(entries, tmp_path, base_url="https://moui.io",
                   grove=_grove(), ctx=_ctx())
    assert not (tmp_path / "archive" / "index.html").exists()
