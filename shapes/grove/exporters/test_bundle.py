"""Tests for bundle collector."""
import json
from bundle import collect_bundle


def test_collect_bundle_structure():
    """Bundle has pages dict, searchIndex list, firstLoadIndex list."""
    pages = {
        "/": {"title": "Home", "main": "<div>index</div>", "layout": "index"},
        "/hello/": {"title": "Hello", "main": "<article>hi</article>", "layout": "article"},
    }
    search_index = [{"title": "Hello", "path": "/hello/", "body": "hi"}]
    first_load_index = [{"title": "Hello", "url_path": "/hello/"}]

    bundle = collect_bundle(pages, search_index, first_load_index)
    parsed = json.loads(bundle)

    assert set(parsed.keys()) == {"pages", "searchIndex", "firstLoadIndex"}
    assert len(parsed["pages"]) == 2
    assert parsed["pages"]["/"]["title"] == "Home"
    assert parsed["pages"]["/hello/"]["layout"] == "article"
    assert parsed["searchIndex"] == search_index
    assert parsed["firstLoadIndex"] == first_load_index


def test_collect_bundle_with_toc():
    """Pages with TOC data include it in the bundle."""
    pages = {
        "/post/": {
            "title": "Post",
            "main": "<article>content</article>",
            "layout": "article",
            "toc": [{"id": "intro", "text": "Intro", "level": 2}],
        },
    }
    bundle = collect_bundle(pages, [], [])
    parsed = json.loads(bundle)
    assert parsed["pages"]["/post/"]["toc"] == [{"id": "intro", "text": "Intro", "level": 2}]


def test_collect_bundle_returns_string():
    """Bundle is a JSON string, not a dict."""
    bundle = collect_bundle({}, [], [])
    assert isinstance(bundle, str)
    json.loads(bundle)  # must parse


def test_collect_bundle_with_asset_manifest():
    """Bundle includes assetManifest when provided."""
    manifest = {
        "assets/photo.png": {
            "source_hash": "abc123",
            "original": {"path": "assets/photo.png", "width": 1600},
            "variants": [{"path": "assets/photo-480w.webp", "width": 480}],
        }
    }
    bundle = collect_bundle({}, [], [], asset_manifest=manifest, asset_salt="dGVzdHNhbHQ=")
    parsed = json.loads(bundle)
    assert parsed["assetManifest"] == manifest
    assert parsed["assetSalt"] == "dGVzdHNhbHQ="


def test_collect_bundle_no_manifest_omits_keys():
    """Bundle without asset_manifest has no asset keys."""
    bundle = collect_bundle({}, [], [])
    parsed = json.loads(bundle)
    assert "assetManifest" not in parsed
    assert "assetSalt" not in parsed
