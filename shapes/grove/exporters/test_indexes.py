"""Tests for grove index generators."""
import json
from indexes import generate_first_load_index, generate_search_index

def _post(title="Test", content_path="test", url_path="/test/",
          excerpt="Excerpt.", publish_date="2026-04-14", tags=None, **kw):
    return {"title": title, "content_path": content_path, "url_path": url_path,
            "excerpt": excerpt, "publish_date": publish_date, "tags": tags or [],
            "body": "Some content here.", **kw}

class TestFirstLoadIndex:
    def test_respects_limit(self):
        posts = [_post(title=f"Post {i}") for i in range(20)]
        raw = generate_first_load_index(posts, limit=12)
        data = json.loads(raw)
        assert len(data) == 12

    def test_excludes_body(self):
        raw = generate_first_load_index([_post()])
        data = json.loads(raw)
        assert "body" not in data[0]

    def test_includes_metadata(self):
        raw = generate_first_load_index([_post()])
        item = json.loads(raw)[0]
        assert item["title"] == "Test"
        assert item["url_path"] == "/test/"
        assert item["excerpt"] == "Excerpt."

class TestSearchIndex:
    def test_includes_tokens(self):
        raw = generate_search_index([_post(body="The quick brown fox")])
        data = json.loads(raw)
        assert "tokens" in data[0]
        assert "quick" in data[0]["tokens"]

    def test_includes_metadata(self):
        raw = generate_search_index([_post()])
        item = json.loads(raw)[0]
        assert item["title"] == "Test"
        assert item["path"] == "test"
