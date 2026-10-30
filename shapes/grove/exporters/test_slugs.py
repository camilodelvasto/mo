"""Tests for grove slug resolver."""
import pytest
from slugs import resolve_slugs, SlugConflictError

def _post(content_path, slug="", _source_path="test.md", **kw):
    return {"content_path": content_path, "slug": slug, "title": "T",
            "published": True, "_source_path": _source_path, **kw}

class TestResolveSlugs:
    def test_empty_slug_uses_content_path(self):
        posts = [_post("architecture/corpus-format")]
        resolved = resolve_slugs(posts)
        assert resolved[0]["url_path"] == "/architecture/corpus-format/"

    def test_explicit_slug_overrides_path(self):
        posts = [_post("deep/nested/file", slug="short-name")]
        resolved = resolve_slugs(posts)
        assert resolved[0]["url_path"] == "/short-name/"

    def test_slug_with_path_segments(self):
        posts = [_post("file", slug="architecture/corpus-format")]
        resolved = resolve_slugs(posts)
        assert resolved[0]["url_path"] == "/architecture/corpus-format/"

    def test_duplicate_slugs_throw(self):
        posts = [
            _post("a", slug="same", _source_path="a.md"),
            _post("b", slug="same", _source_path="b.md"),
        ]
        with pytest.raises(SlugConflictError, match="same"):
            resolve_slugs(posts)

    def test_slug_and_path_collision_throws(self):
        posts = [
            _post("welcome", _source_path="welcome.md"),
            _post("deep/file", slug="welcome", _source_path="deep/file.md"),
        ]
        with pytest.raises(SlugConflictError, match="welcome"):
            resolve_slugs(posts)

    def test_section_index_url(self):
        posts = [_post("architecture", is_section_index=True)]
        resolved = resolve_slugs(posts)
        assert resolved[0]["url_path"] == "/architecture/"
