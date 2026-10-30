"""Tests for grove collection loader."""
import pytest
from pathlib import Path
from collections_mod import load_collections, resolve_collection_posts, CollectionError


def _write_collection(tmp_path, filename, content):
    p = tmp_path / filename
    p.write_text(content)
    return p


class TestLoadCollections:
    def test_loads_yaml(self, tmp_path):
        _write_collection(tmp_path, "getting-started.yaml", """
id: getting-started
title: "Getting Started"
posts:
  - welcome
""")
        colls = load_collections(tmp_path)
        assert len(colls) == 1
        assert colls[0]["id"] == "getting-started"

    def test_missing_id_throws(self, tmp_path):
        _write_collection(tmp_path, "bad.yaml", "title: X\nposts:\n  - a")
        with pytest.raises(CollectionError, match="id"):
            load_collections(tmp_path)

    def test_missing_title_throws(self, tmp_path):
        _write_collection(tmp_path, "bad.yaml", "id: x\nposts:\n  - a")
        with pytest.raises(CollectionError, match="title"):
            load_collections(tmp_path)

    def test_missing_posts_throws(self, tmp_path):
        _write_collection(tmp_path, "bad.yaml", "id: x\ntitle: X")
        with pytest.raises(CollectionError, match="posts"):
            load_collections(tmp_path)

    def test_missing_dir_returns_empty(self, tmp_path):
        assert load_collections(tmp_path / "nonexistent") == []

    def test_sorted_by_filename(self, tmp_path):
        _write_collection(tmp_path, "b-second.yaml", "id: b\ntitle: B\nposts:\n  - x")
        _write_collection(tmp_path, "a-first.yaml", "id: a\ntitle: A\nposts:\n  - x")
        colls = load_collections(tmp_path)
        assert colls[0]["id"] == "a"
        assert colls[1]["id"] == "b"

    def test_source_path_attached(self, tmp_path):
        _write_collection(tmp_path, "test.yaml", "id: t\ntitle: T\nposts:\n  - x")
        colls = load_collections(tmp_path)
        assert "_source_path" in colls[0]


class TestResolveCollectionPosts:
    def test_resolves_posts(self):
        coll = {"id": "test", "posts": ["welcome", "about"]}
        posts_by_path = {
            "welcome": {"title": "Welcome", "content_path": "welcome"},
            "about": {"title": "About", "content_path": "about"},
        }
        resolved = resolve_collection_posts(coll, posts_by_path)
        assert len(resolved) == 2
        assert resolved[0]["title"] == "Welcome"

    def test_missing_post_throws(self):
        coll = {"id": "test", "posts": ["nonexistent"]}
        with pytest.raises(CollectionError, match="nonexistent"):
            resolve_collection_posts(coll, {})

    def test_preserves_order(self):
        coll = {"id": "test", "posts": ["b", "a"]}
        posts_by_path = {
            "a": {"title": "A", "content_path": "a"},
            "b": {"title": "B", "content_path": "b"},
        }
        resolved = resolve_collection_posts(coll, posts_by_path)
        assert resolved[0]["title"] == "B"
        assert resolved[1]["title"] == "A"
