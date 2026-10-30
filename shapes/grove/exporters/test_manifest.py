"""Tests for manifest generation."""
import json
from pathlib import Path
from manifest import build_manifest, write_manifest


def _post(route="/welcome/", title="Welcome", excerpt="Hello.", date="2026-04-28",
          section="", tags=None, priority=1, blob="abc123.bin", hash="abc123",
          layout="article", theme=""):
    return {
        "route": route, "title": title, "excerpt": excerpt,
        "publish_date": date, "section": section, "tags": tags or [],
        "priority": priority, "type": "post",
        "blob": blob, "hash": hash, "layout": layout, "theme": theme,
        "og": {"title": title, "description": excerpt, "image": ""},
    }


def test_manifest_has_version():
    m = build_manifest(
        entries=[_post()], assets=[], build_hash="abc123",
        loading_strategy="progressive", priority_count=12,
    )
    assert m["version"] == "abc123"


def test_manifest_has_entries():
    m = build_manifest(
        entries=[_post(), _post(route="/other/", blob="def456.bin", hash="def456")],
        assets=[], build_hash="abc",
        loading_strategy="progressive", priority_count=12,
    )
    assert len(m["entries"]) == 2
    assert m["entries"][0]["route"] == "/welcome/"
    assert m["entries"][0]["blob"] == "abc123.bin"


def test_manifest_entry_has_card_metadata():
    m = build_manifest(
        entries=[_post(title="My Post", excerpt="Summary.", date="2026-04-28",
                       section="arch", tags=["a", "b"])],
        assets=[], build_hash="abc",
        loading_strategy="progressive", priority_count=12,
    )
    entry = m["entries"][0]
    assert entry["title"] == "My Post"
    assert entry["excerpt"] == "Summary."
    assert entry["date"] == "2026-04-28"
    assert entry["section"] == "arch"
    assert entry["tags"] == ["a", "b"]


def test_manifest_has_loading_config():
    m = build_manifest(
        entries=[], assets=[], build_hash="abc",
        loading_strategy="eager", priority_count=5,
    )
    assert m["loading"]["strategy"] == "eager"
    assert m["loading"]["priority_count"] == 5


def test_manifest_encrypted_false():
    m = build_manifest(
        entries=[], assets=[], build_hash="abc",
        loading_strategy="progressive", priority_count=12,
    )
    assert m["encrypted"] is False


def test_manifest_has_assets():
    assets = [{"original_path": "assets/photo.png", "blob": "c4d9.bin",
               "hash": "c4d9", "mime": "image/png", "width": 800, "height": 600}]
    m = build_manifest(
        entries=[], assets=assets, build_hash="abc",
        loading_strategy="progressive", priority_count=12,
    )
    assert len(m["assets"]) == 1
    assert m["assets"][0]["mime"] == "image/png"


def test_manifest_entry_has_layout():
    m = build_manifest(
        entries=[_post(layout="article")],
        assets=[], build_hash="abc",
        loading_strategy="progressive", priority_count=12,
    )
    assert m["entries"][0]["layout"] == "article"


def test_manifest_entry_has_theme():
    entry = _post()
    entry["theme"] = "dark-override"
    m = build_manifest(
        entries=[entry],
        assets=[], build_hash="abc",
        loading_strategy="progressive", priority_count=12,
    )
    assert m["entries"][0]["theme"] == "dark-override"


def test_manifest_entry_theme_defaults_to_empty():
    m = build_manifest(
        entries=[_post()],
        assets=[], build_hash="abc",
        loading_strategy="progressive", priority_count=12,
    )
    assert m["entries"][0]["theme"] == ""


def test_write_manifest_creates_json(tmp_path):
    m = build_manifest(
        entries=[_post()], assets=[], build_hash="abc",
        loading_strategy="progressive", priority_count=12,
    )
    write_manifest(m, tmp_path)
    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert loaded["version"] == "abc"
    assert len(loaded["entries"]) == 1
