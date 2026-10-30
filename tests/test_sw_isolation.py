"""Tests for SW scope isolation — declaration injection and gravestone."""
import json
import sys
import yaml
from pathlib import Path

# Add grove exporters to path for import
_grove_exporters = Path(__file__).resolve().parent.parent / "shapes" / "grove" / "exporters"
if str(_grove_exporters) not in sys.path:
    sys.path.insert(0, str(_grove_exporters))

from build import (
    _collect_owned_pages,
    _collect_owned_assets,
    _collect_sibling_paths,
    _collect_chat_spa_roots,
    _collect_optional_static,
    _inject_sw_declarations,
    _write_gravestone_sw,
    _GROVE_DYNAMIC_PATHS,
    _GRAVESTONE_SW,
)


def _make_sw(tmp_path):
    """Create a minimal sw.js with all sentinels."""
    sw = tmp_path / "sw.js"
    sw.write_text(
        "const BUILD_VERSION = 'dev';\n"
        "const OPTIONAL_STATIC_ASSETS = [];\n"
        "const OWNED_PAGES = [];\n"
        "const OWNED_SPA_ROOTS = [];\n"
        "const OWNED_DYNAMIC_PATHS = [];\n"
        "const OWNED_ASSETS = [];\n"
        "const SIBLING_PATHS = [];\n"
    )
    return sw


class TestCollectOwnedPages:
    def test_includes_root_and_archive(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        pages = _collect_owned_pages([], dist)
        assert '/' in pages
        assert '/archive/' in pages

    def test_includes_post_url_paths(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        posts = [
            {"url_path": "/about/", "title": "About"},
            {"url_path": "/on-joy/", "title": "On Joy"},
        ]
        pages = _collect_owned_pages(posts, dist)
        assert '/about/' in pages
        assert '/on-joy/' in pages

    def test_includes_section_indexes(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        section = dist / "essays"
        section.mkdir()
        (section / "index.html").write_text("<h1>Essays</h1>")
        pages = _collect_owned_pages([], dist)
        assert '/essays/' in pages

    def test_excludes_infra_dirs(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        for d in ('theme', 'assets', 'shell-web', 'shell-tauri', 'archive'):
            p = dist / d
            p.mkdir()
            (p / "index.html").write_text("x")
        pages = _collect_owned_pages([], dist)
        # archive is added explicitly, not from dir scan
        assert pages.count('/archive/') == 1
        assert '/theme/' not in pages
        assert '/assets/' not in pages

    def test_includes_collections(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        c = dist / "c" / "favorites"
        c.mkdir(parents=True)
        pages = _collect_owned_pages([], dist)
        assert '/c/favorites/' in pages


class TestCollectOwnedAssets:
    def test_collects_original_and_variants(self):
        manifest = {
            "assets/photo.png": {
                "original": {"path": "assets/photo.png", "width": 1200},
                "variants": [
                    {"path": "assets/photo-800w.webp", "width": 800},
                    {"path": "assets/photo-800w.png", "width": 800},
                ],
            }
        }
        paths = _collect_owned_assets(manifest)
        assert '/assets/photo.png' in paths
        assert '/assets/photo-800w.webp' in paths
        assert '/assets/photo-800w.png' in paths

    def test_empty_manifest(self):
        assert _collect_owned_assets({}) == []

    def test_passthrough_assets(self):
        manifest = {
            "assets/diagram.svg": {
                "passthrough": True,
                "original": {"path": "assets/diagram.svg"},
                "variants": [],
            }
        }
        paths = _collect_owned_assets(manifest)
        assert '/assets/diagram.svg' in paths


class TestInjectSwDeclarations:
    def test_injects_all_declarations(self, tmp_path):
        sw = _make_sw(tmp_path)
        pages = ['/', '/about/', '/archive/']
        dynamic = ['/feed.xml', '/sitemap.xml']
        assets = ['/assets/photo.png']
        _inject_sw_declarations(tmp_path, pages, dynamic, assets)

        text = sw.read_text()
        assert "const OWNED_PAGES = [" in text
        assert '"/about/"' in text
        assert "const OWNED_DYNAMIC_PATHS = [" in text
        assert '"/feed.xml"' in text
        assert "const OWNED_ASSETS = [" in text
        assert '"/assets/photo.png"' in text

    def test_sentinels_replaced(self, tmp_path):
        sw = _make_sw(tmp_path)
        _inject_sw_declarations(tmp_path, ['/'], ['/feed.xml'], ['/assets/x.png'])
        text = sw.read_text()
        assert 'const OWNED_PAGES = [];' not in text
        assert 'const OWNED_DYNAMIC_PATHS = [];' not in text
        assert 'const OWNED_ASSETS = [];' not in text

    def test_injects_spa_roots(self, tmp_path):
        sw = _make_sw(tmp_path)
        _inject_sw_declarations(tmp_path, ['/'], [], [],
                                spa_roots=['/advisor', '/audiencias'])
        text = sw.read_text()
        assert 'const OWNED_SPA_ROOTS = ["/advisor", "/audiencias"];' in text

    def test_spa_roots_default_empty(self, tmp_path):
        sw = _make_sw(tmp_path)
        _inject_sw_declarations(tmp_path, ['/'], [], [])
        assert 'const OWNED_SPA_ROOTS = [];' in sw.read_text()

    def test_injects_optional_static(self, tmp_path):
        sw = _make_sw(tmp_path)
        _inject_sw_declarations(tmp_path, ['/'], [], [],
                                optional_static=['/manifest.json'])
        assert 'const OPTIONAL_STATIC_ASSETS = ["/manifest.json"];' in sw.read_text()

    def test_optional_static_default_empty(self, tmp_path):
        sw = _make_sw(tmp_path)
        _inject_sw_declarations(tmp_path, ['/'], [], [])
        assert 'const OPTIONAL_STATIC_ASSETS = [];' in sw.read_text()


class TestCollectOptionalStatic:
    def test_lists_manifest_when_present(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "manifest.json").write_text("{}")
        assert _collect_optional_static(dist) == ['/manifest.json']

    def test_empty_when_manifest_absent(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        assert _collect_optional_static(dist) == []


class TestCollectSiblingPaths:
    def _make_targets(self, tmp_path, targets: dict):
        """Create target YAML files. targets = {relative_path: yaml_dict}."""
        targets_dir = tmp_path / "infrastructure" / "targets"
        for rel_path, data in targets.items():
            f = targets_dir / rel_path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(yaml.dump(data))

    def test_finds_sibling_on_same_domain(self, tmp_path):
        self._make_targets(tmp_path, {
            "website/en.yaml": {
                "content": "website/en",
                "shape": "grove",
                "environments": {
                    "prod": {"domain": "www.moui.io", "base_path": "/"},
                },
            },
            "decks/pitch.yaml": {
                "content": "decks/pitch",
                "shape": "deck",
                "environments": {
                    "prod": {"domain": "www.moui.io", "base_path": "/pitch"},
                },
            },
        })
        siblings = _collect_sibling_paths(tmp_path, "https://www.moui.io/")
        assert "/pitch/" in siblings

    def test_ignores_different_domain(self, tmp_path):
        self._make_targets(tmp_path, {
            "website/en.yaml": {
                "content": "website/en",
                "shape": "grove",
                "environments": {
                    "prod": {"domain": "www.moui.io", "base_path": "/"},
                },
            },
            "other.yaml": {
                "content": "other",
                "shape": "grove",
                "environments": {
                    "prod": {"domain": "other.example.com", "base_path": "/blog"},
                },
            },
        })
        siblings = _collect_sibling_paths(tmp_path, "https://www.moui.io/")
        assert siblings == []

    def test_excludes_own_path(self, tmp_path):
        self._make_targets(tmp_path, {
            "website/en.yaml": {
                "content": "website/en",
                "shape": "grove",
                "environments": {
                    "prod": {"domain": "www.moui.io", "base_path": "/"},
                },
            },
        })
        siblings = _collect_sibling_paths(tmp_path, "https://www.moui.io/")
        assert siblings == []

    def test_no_corpus_root(self):
        assert _collect_sibling_paths(None, "https://www.moui.io/") == []

    def test_subpath_grove_excludes_non_nested_siblings(self, tmp_path):
        # A grove under /hub must NOT list the root grove ('/') or
        # peers ('/es') as siblings: they live outside its SW scope, and '/'
        # is a prefix of every in-scope path — listing it makes the SW pass
        # through its own routes (the chat deep-link bug).
        self._make_targets(tmp_path, {
            "website/en.yaml": {"content": "website/en", "shape": "grove",
                "environments": {"prod": {"domain": "www.moui.io", "base_path": "/"}}},
            "website/es.yaml": {"content": "website/es", "shape": "grove",
                "environments": {"prod": {"domain": "www.moui.io", "base_path": "/es"}}},
            "clients/hub.yaml": {"content": "clients/hub", "shape": "grove",
                "environments": {"prod": {"domain": "www.moui.io", "base_path": "/hub"}}},
        })
        siblings = _collect_sibling_paths(tmp_path, "https://www.moui.io/hub")
        assert siblings == []

    def test_subpath_grove_includes_nested_sibling_relative(self, tmp_path):
        # A truly nested sub-grove IS a sibling, expressed relative to this
        # grove's base (so the SW's BASE_PATH + p yields the right absolute path).
        self._make_targets(tmp_path, {
            "clients/hub.yaml": {"content": "clients/hub", "shape": "grove",
                "environments": {"prod": {"domain": "www.moui.io", "base_path": "/hub"}}},
            "clients/sub.yaml": {"content": "clients/sub", "shape": "grove",
                "environments": {"prod": {"domain": "www.moui.io", "base_path": "/hub/sub"}}},
        })
        siblings = _collect_sibling_paths(tmp_path, "https://www.moui.io/hub")
        assert siblings == ['/sub/']

    def test_injects_into_sw(self, tmp_path):
        sw = _make_sw(tmp_path)
        _inject_sw_declarations(tmp_path, ['/'], ['/feed.xml'], [],
                                sibling_paths=['/pitch/'])
        text = sw.read_text()
        assert 'const SIBLING_PATHS = ["/pitch/"]' in text


class TestCollectChatSpaRoots:
    def _grove(self):
        return {"features": [
            {"id": "advisor", "type": "chat"},
            {"id": "gallery", "type": "album"},
        ]}

    def test_returns_route_of_page_mounting_a_chat(self):
        grove = self._grove()
        pages = [
            {"route": "/advisor", "body": [{"feature": "advisor"}]},
            {"route": "/about", "body": [{"text": "hi"}]},
        ]
        assert _collect_chat_spa_roots(pages, grove) == ["/advisor"]

    def test_ignores_pages_that_mount_no_chat(self):
        grove = self._grove()
        pages = [
            {"route": "/gallery", "body": [{"feature": "gallery"}]},
            {"route": "/about", "body": [{"text": "hi"}]},
        ]
        assert _collect_chat_spa_roots(pages, grove) == []

    def test_collects_every_chat_page_in_order(self):
        grove = {"features": [
            {"id": "advisor", "type": "chat"},
            {"id": "audiencias", "type": "chat"},
        ]}
        pages = [
            {"route": "/advisor", "body": [{"feature": "advisor"}]},
            {"route": "/audiencias", "body": [{"feature": "audiencias"}]},
        ]
        assert _collect_chat_spa_roots(pages, grove) == ["/advisor", "/audiencias"]


class TestGravestoneSw:
    def test_writes_gravestone(self, tmp_path):
        _write_gravestone_sw(tmp_path)
        text = (tmp_path / "sw.js").read_text()
        assert 'self.registration.unregister()' in text
        # No fetch event listener — intentional
        assert "addEventListener('fetch'" not in text

    def test_gravestone_replaces_existing(self, tmp_path):
        sw = _make_sw(tmp_path)
        assert 'BUILD_VERSION' in sw.read_text()
        _write_gravestone_sw(tmp_path)
        text = sw.read_text()
        assert 'BUILD_VERSION' not in text
        assert 'unregister()' in text
