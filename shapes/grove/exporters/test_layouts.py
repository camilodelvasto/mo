"""Tests for grove layout templates."""
import pytest
from layouts import article_layout, quote_layout, landing_layout, minimal_layout

def _post(title="Test", body_html="<p>Hello</p>", publish_date="2026-04-14", **kw):
    return {"title": title, "body_html": body_html, "publish_date": publish_date,
            "tags": ["test"], "excerpt": "A test.", "url_path": "/test/",
            "content_path": "test", **kw}

class TestArticleLayout:
    def test_has_header_and_time(self):
        html = article_layout(_post())
        assert "<h1" in html
        assert "Test" in html
        assert "<time" in html

    def test_has_toc_placeholder(self):
        html = article_layout(_post())
        assert "post-body" in html

    def test_has_tags(self):
        html = article_layout(_post(tags=["moui", "architecture"]))
        assert "moui" in html

class TestQuoteLayout:
    def test_has_blockquote_class(self):
        html = quote_layout(_post())
        assert "quote-layout" in html

    def test_minimal_chrome(self):
        html = quote_layout(_post())
        assert "toc" not in html.lower()

class TestLandingLayout:
    def test_full_bleed(self):
        html = landing_layout(_post())
        assert "landing-layout" in html

    def test_no_standard_header(self):
        html = landing_layout(_post())
        assert '<header>' not in html or 'landing' in html

class TestMinimalLayout:
    def test_body_only(self):
        html = minimal_layout(_post())
        assert "minimal-layout" in html
        assert "post-body" in html
        assert "<time" not in html


class TestRequiredFields:
    def test_missing_body_html_throws(self):
        post = {"title": "Test", "publish_date": "2026-04-14", "tags": ["test"]}
        with pytest.raises(KeyError):
            article_layout(post)

    def test_missing_title_throws(self):
        post = {"body_html": "<p>Hello</p>"}
        with pytest.raises(KeyError):
            article_layout(post)
