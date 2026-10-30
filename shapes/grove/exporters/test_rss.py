"""Tests for grove RSS generator."""
import json
from rss import generate_rss_xml, generate_json_feed

BASE_URL = "https://example.com"

def _post(title="Test", url_path="/test/", excerpt="Excerpt.", publish_date="2026-04-14", **kw):
    return {"title": title, "url_path": url_path, "excerpt": excerpt,
            "publish_date": publish_date, "content_path": "test", **kw}

def _grove():
    return {"title": "My Grove", "description": "A grove.",
            "lang": "en", "rss": {"max_items": 20}}

class TestGenerateRssXml:
    def test_valid_xml(self):
        xml = generate_rss_xml([_post()], _grove(), BASE_URL)
        assert '<?xml version="1.0"' in xml
        assert '<rss version="2.0"' in xml
        assert "<title>My Grove</title>" in xml
        assert "<title>Test</title>" in xml

    def test_respects_max_items(self):
        posts = [_post(title=f"Post {i}") for i in range(25)]
        xml = generate_rss_xml(posts, _grove(), BASE_URL)
        assert xml.count("<item>") == 20

    def test_link_uses_base_url(self):
        xml = generate_rss_xml([_post()], _grove(), BASE_URL)
        assert "https://example.com/test/" in xml

class TestGenerateJsonFeed:
    def test_valid_json(self):
        raw = generate_json_feed([_post()], _grove(), BASE_URL)
        feed = json.loads(raw)
        assert feed["version"] == "https://jsonfeed.org/version/1.1"
        assert feed["title"] == "My Grove"
        assert len(feed["items"]) == 1

    def test_item_structure(self):
        raw = generate_json_feed([_post()], _grove(), BASE_URL)
        item = json.loads(raw)["items"][0]
        assert item["title"] == "Test"
        assert item["url"] == "https://example.com/test/"
