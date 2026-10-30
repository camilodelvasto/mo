"""Tests for grove sitemap generator."""
from sitemap import generate_sitemap

def _post(url_path="/test/", publish_date="2026-04-14"):
    return {"url_path": url_path, "publish_date": publish_date, "title": "T"}

class TestGenerateSitemap:
    def test_valid_xml(self):
        xml = generate_sitemap([_post()], "https://example.com")
        assert '<?xml version="1.0"' in xml
        assert '<urlset' in xml
        assert 'https://example.com/test/' in xml

    def test_includes_lastmod(self):
        xml = generate_sitemap([_post()], "https://example.com")
        assert '<lastmod>2026-04-14</lastmod>' in xml

    def test_multiple_posts(self):
        posts = [_post(url_path="/a/"), _post(url_path="/b/")]
        xml = generate_sitemap(posts, "https://example.com")
        assert xml.count("<url>") == 2
