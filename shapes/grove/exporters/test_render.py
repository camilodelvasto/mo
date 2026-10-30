"""Tests for grove HTML renderer."""
import json
import pytest
from render import render_post, render_index_page, render_archive_page, render_post_fragment, render_index_fragment, render_archive_fragment

def _post(title="Test", body="# Hello\n\nWorld.", url_path="/test/", layout="article", encrypted=False, **kw):
    return {"title": title, "body": body, "url_path": url_path, "layout": layout,
            "excerpt": "A test.", "publish_date": "2026-04-14", "tags": ["test"],
            "content_path": "test", "published": True, "encrypted": encrypted, **kw}

def _grove():
    return {
        "id": "test-grove", "title": "Test Grove", "lang": "en",
        "og": {"title": "Test", "description": "A test.", "image": "og.png"},
        "defaults": {"layout": "article"},
        "rss": {"enabled": True},
        "header": {
            "actions": [
                {"label": "Archive", "feature": "archive", "style": "ghost"},
                {"label": "Search", "feature": "search", "style": "accent", "icon": "search"},
            ]
        },
    }

def _ctx(base_url="https://example.com", base_path="", theme_css=":root { --color-bg-resolved: #fff; }"):
    from pathlib import Path
    icons_dir = Path(__file__).resolve().parent.parent / "icons"
    return {
        "base_url": base_url, "base_path": base_path, "theme_css": theme_css,
        "on_clear": "reload",
        "icons_dir": icons_dir,
        "strings": {
            "toggle_theme": "Toggle theme", "clear_site": "Clear site data",
            "skip_to_content": "Skip to content",
            "search_placeholder": "Search posts...", "search_no_results": "No results found.",
            "search_aria": "Search", "search_input_aria": "Search posts",
            "toc": "Table of Contents", "reading_progress": "Reading progress",
            "gate_subtitle": "Private.", "gate_label": "Code", "gate_submit": "Unlock",
            "gate_error": "Wrong.", "load_error_title": "Error", "load_error_body": "Failed.",
        },
    }

class TestRenderPost:
    def test_produces_html(self):
        html = render_post(_post(), _grove(), _ctx())
        assert "<!DOCTYPE html>" in html
        assert "<h1" in html
        assert "Hello" in html

    def test_injects_og_tags(self):
        html = render_post(_post(), _grove(), _ctx())
        assert 'og:title' in html

    def test_includes_lang(self):
        html = render_post(_post(), _grove(), _ctx())
        assert 'lang="en"' in html

    def test_layout_in_body_attribute(self):
        html = render_post(_post(layout="quote"), _grove(), _ctx())
        assert 'data-layout="quote"' in html

    def test_grove_og_used_when_post_has_none(self):
        html = render_post(_post(), _grove(), _ctx())
        assert "A test." in html

    def test_post_og_overrides_grove(self):
        post = _post(og={"title": "Custom", "description": "Custom desc", "image": "custom.png"})
        html = render_post(post, _grove(), _ctx())
        assert "Custom desc" in html

    def test_post_og_merges_with_grove(self):
        """Post OG layers on top of grove OG — unset fields inherit from grove."""
        post = _post(og={"title": "Custom title", "description": "Custom desc"})
        html = render_post(post, _grove(), _ctx(base_url="https://example.com"))
        assert "Custom title" in html
        assert "Custom desc" in html
        # image inherited from grove
        assert 'content="https://example.com/og.png"' in html

    def test_post_og_empty_strings_inherit_grove(self):
        """Empty strings in post OG don't clobber grove values."""
        post = _post(og={"title": "", "image": "", "description": "Only this"})
        html = render_post(post, _grove(), _ctx(base_url="https://example.com"))
        assert "Only this" in html
        # title and image fall through to grove
        assert 'content="Test"' in html
        assert 'content="https://example.com/og.png"' in html

    def test_post_og_twitter_card_overrides_grove(self):
        """Post-level twitter_card layers over grove-level."""
        grove = _grove()
        grove["og"]["twitter_card"] = "summary"
        post = _post(og={"twitter_card": "summary_large_image"})
        html = render_post(post, grove, _ctx())
        assert "summary_large_image" in html

    def test_og_image_is_absolute_url(self):
        html = render_post(_post(), _grove(), _ctx(base_url="https://example.com"))
        assert 'content="https://example.com/og.png"' in html

    def test_og_url_set_per_post(self):
        html = render_post(_post(url_path="/hello/"), _grove(), _ctx(base_url="https://example.com"))
        assert 'og:url' in html
        assert 'content="https://example.com/hello/"' in html

    def test_og_type_article_for_post(self):
        html = render_post(_post(), _grove(), _ctx())
        assert 'og:type' in html
        assert 'content="article"' in html

    def test_og_type_website_for_index(self):
        html = render_index_page([_post()], _grove(), _ctx())
        assert 'content="website"' in html

    def test_twitter_card_rendered(self):
        grove = _grove()
        grove["og"]["twitter_card"] = "summary_large_image"
        html = render_post(_post(), grove, _ctx())
        assert 'twitter:card' in html
        assert 'summary_large_image' in html

    def test_skip_link_present(self):
        html = render_post(_post(), _grove(), _ctx())
        assert 'class="skip-link"' in html
        assert 'href="#main"' in html

    def test_rss_alternate_link(self):
        html = render_post(_post(), _grove(), _ctx())
        assert 'application/rss+xml' in html

class TestRenderIndexPage:
    def test_produces_html(self):
        html = render_index_page([_post()], _grove(), _ctx(), page_title="Home")
        assert "<!DOCTYPE html>" in html

    def test_contains_post_card(self):
        html = render_index_page([_post(title="My Post")], _grove(), _ctx())
        assert "My Post" in html

class TestLayoutIntegration:
    def test_quote_layout_applied(self):
        html = render_post(_post(layout="quote"), _grove(), _ctx())
        assert 'data-layout="quote"' in html
        assert "quote-layout" in html

    def test_article_has_toc_data(self):
        post = _post(body="## Section One\n\nText.\n\n## Section Two\n\nMore.")
        html = render_post(post, _grove(), _ctx())
        assert "toc-data" in html

class TestArchivePage:
    def test_archive_has_all_posts(self):
        posts = [_post(title=f"Post {i}") for i in range(5)]
        html = render_archive_page(posts, _grove(), _ctx())
        for i in range(5):
            assert f"Post {i}" in html
        assert "Archive" in html


class TestPageShellIntegration:
    def test_post_has_header(self):
        html = render_post(_post(), _grove(), _ctx())
        assert "site-header" in html

    def test_post_has_footer(self):
        html = render_post(_post(), _grove(), _ctx())
        assert "site-footer" in html

    def test_index_has_header(self):
        html = render_index_page([_post()], _grove(), _ctx())
        assert "site-header" in html

    def test_archive_has_header(self):
        html = render_archive_page([_post()], _grove(), _ctx())
        assert "site-header" in html


class TestRequiredFields:
    def test_missing_grove_defaults_throws(self):
        grove = _grove()
        del grove["defaults"]
        post = _post()
        del post["layout"]
        with pytest.raises(KeyError):
            render_post(post, grove, _ctx())

    def test_missing_grove_og_throws(self):
        grove = _grove()
        del grove["og"]
        post = _post()
        post.pop("og", None)
        with pytest.raises(KeyError):
            render_post(post, grove, _ctx())


class TestEncryptedPost:
    def test_encrypted_post_has_envelope(self):
        from encrypt import make_encryptor, generate_mnemonic
        enc = make_encryptor(generate_mnemonic())
        post = _post(encrypted=True)
        html = render_post(post, _grove(), _ctx(), encryptor=enc)
        assert 'id="grove-envelope"' in html
        assert 'id="grove-gate"' in html

    def test_encrypted_post_shell_intact(self):
        from encrypt import make_encryptor, generate_mnemonic
        enc = make_encryptor(generate_mnemonic())
        post = _post(encrypted=True)
        html = render_post(post, _grove(), _ctx(), encryptor=enc)
        assert "site-header" in html
        assert "site-footer" in html
        assert "app.js" in html

    def test_encrypted_post_body_not_in_html(self):
        from encrypt import make_encryptor, generate_mnemonic
        enc = make_encryptor(generate_mnemonic())
        post = _post(encrypted=True, body="# SuperSecretContent\n\nThis is secret.")
        html = render_post(post, _grove(), _ctx(), encryptor=enc)
        assert "SuperSecretContent" not in html
        assert "This is secret" not in html

    def test_encrypted_post_title_visible(self):
        from encrypt import make_encryptor, generate_mnemonic
        enc = make_encryptor(generate_mnemonic())
        post = _post(encrypted=True, title="Public Title")
        html = render_post(post, _grove(), _ctx(), encryptor=enc)
        assert "Public Title" in html

    def test_unencrypted_post_unchanged(self):
        post = _post(encrypted=False)
        html = render_post(post, _grove(), _ctx(), encryptor=None)
        assert 'id="grove-envelope"' not in html
        assert "Hello" in html

    def test_envelope_is_valid_json(self):
        from encrypt import make_encryptor, generate_mnemonic
        enc = make_encryptor(generate_mnemonic())
        post = _post(encrypted=True)
        html = render_post(post, _grove(), _ctx(), encryptor=enc)
        start = html.index('id="grove-envelope">') + len('id="grove-envelope">')
        end = html.index('</script>', start)
        envelope = json.loads(html[start:end])
        assert envelope["encrypted"] is True
        assert envelope["key_id"] is None


class TestImageTransformation:
    def test_post_with_image_gets_picture_element(self):
        manifest = {
            "assets/photo.png": {
                "source_hash": "abc",
                "post_slugs": ["test"],
                "passthrough": False,
                "encrypted": False,
                "original": {"path": "assets/photo.png", "width": 1600,
                             "height": 900, "format": "png", "og_safe": True},
                "variants": [
                    {"path": "assets/photo-480w.webp", "width": 480, "format": "webp", "encrypted": False},
                    {"path": "assets/photo-480w.png", "width": 480, "format": "png", "encrypted": False},
                ],
            }
        }
        post = _post(body="![A photo](assets/photo.png)\n")
        html = render_post(post, _grove(), _ctx(), manifest=manifest)
        assert "<picture>" in html
        assert "<figure>" in html
        assert "480w" in html
        assert 'type="image/webp"' in html

    def test_post_without_manifest_no_picture(self):
        post = _post(body="![A photo](assets/photo.png)\n")
        html = render_post(post, _grove(), _ctx())
        assert "<picture>" not in html

    def test_og_image_resolved_from_manifest(self):
        manifest = {
            "og.png": {
                "source_hash": "abc",
                "post_slugs": [],
                "passthrough": False,
                "encrypted": False,
                "original": {"path": "assets/og.png", "width": 500,
                             "height": 158, "format": "png", "og_safe": True},
                "variants": [],
            }
        }
        html = render_post(_post(), _grove(), _ctx(base_url="https://example.com"),
                           manifest=manifest)
        assert 'content="https://example.com/assets/og.png"' in html


class TestRenderPostFragment:
    def test_returns_layout_html_not_full_page(self):
        html = render_post_fragment(_post(), _grove(), _ctx())
        assert "<!DOCTYPE" not in html
        assert "<html" not in html
        assert "<head>" not in html
        assert "site-header" not in html
        assert "site-footer" not in html

    def test_contains_article_layout(self):
        html = render_post_fragment(_post(), _grove(), _ctx())
        assert "article-layout" in html

    def test_contains_post_body(self):
        html = render_post_fragment(_post(body="Hello world."), _grove(), _ctx())
        assert "Hello world." in html

    def test_contains_toc_for_article(self):
        body = "## Section One\nText.\n## Section Two\nMore text."
        html = render_post_fragment(_post(body=body), _grove(), _ctx())
        assert "toc-data" in html

    def test_no_toc_for_non_article(self):
        html = render_post_fragment(_post(layout="minimal"), _grove(), _ctx())
        assert "toc-data" not in html


class TestRenderIndexFragment:
    def test_returns_feed_grid_not_full_page(self):
        html = render_index_fragment([_post()], _grove(), _ctx())
        assert "feed-grid" in html
        assert "<!DOCTYPE" not in html
        assert "site-header" not in html


class TestRenderArchiveFragment:
    def test_returns_archive_not_full_page(self):
        html = render_archive_fragment([_post()], _grove(), _ctx())
        assert "Archive" in html
        assert "<!DOCTYPE" not in html
        assert "site-header" not in html


class TestOgImageWarnings:
    def test_missing_og_image_logs_warning(self, capsys):
        post = _post(og={"title": "T", "description": "D", "image": "assets/missing.png"})
        manifest = {}
        render_post(post, _grove(), _ctx(), manifest=manifest)
        captured = capsys.readouterr()
        assert "build warn" in captured.out
        assert "missing.png" in captured.out
        assert "not found in image manifest" in captured.out

    def test_external_og_image_no_warning(self, capsys):
        post = _post(og={"title": "T", "description": "D",
                         "image": "https://example.com/photo.png"})
        render_post(post, _grove(), _ctx(), manifest={})
        captured = capsys.readouterr()
        assert "build warn" not in captured.out

    def test_og_image_in_manifest_no_warning(self, capsys):
        manifest = {
            "og.png": {
                "source_hash": "abc",
                "post_slugs": [],
                "passthrough": False,
                "encrypted": False,
                "original": {"path": "assets/og.png", "width": 1200,
                             "height": 630, "format": "png", "og_safe": True},
                "variants": [],
            }
        }
        render_post(_post(), _grove(), _ctx(), manifest=manifest)
        captured = capsys.readouterr()
        assert "build warn" not in captured.out
