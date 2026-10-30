"""Tests for the deck build module."""
import base64
import json
import shutil
from pathlib import Path

import pytest
import yaml


def test_derive_build_path_strips_content_prefix_and_extension():
    from shapes.deck.exporters.build import derive_build_path

    corpus_root = Path("/corpus")
    content_path = Path("/corpus/content/business/sensata/pitch.yaml")
    result = derive_build_path(content_path, corpus_root)
    assert result == Path("/corpus/.corpus/shapes/deck/builds/business/sensata/pitch")


def test_derive_build_path_handles_nested_paths():
    from shapes.deck.exporters.build import derive_build_path

    corpus_root = Path("/corpus")
    content_path = Path("/corpus/content/personal/talks/pycon.yaml")
    result = derive_build_path(content_path, corpus_root)
    assert result == Path("/corpus/.corpus/shapes/deck/builds/personal/talks/pycon")


def test_derive_build_path_handles_md_extension():
    from shapes.deck.exporters.build import derive_build_path

    corpus_root = Path("/corpus")
    content_path = Path("/corpus/content/notes/hello.md")
    result = derive_build_path(content_path, corpus_root)
    assert result == Path("/corpus/.corpus/shapes/deck/builds/notes/hello")


def _make_corpus(tmp_path):
    """Create a minimal corpus with a deck shape and content file."""
    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test", "shapes": {
            "deck": {"shape": "deck", "version": "0.4.0", "local": True}
        }
    }))

    core = tmp_path / "shapes" / "deck" / "renderer" / "core"
    core.mkdir(parents=True)
    (core / "index.html").write_text("<html><body></body></html>")
    (core / "app.js").write_text("// app")
    (core / "renderer.js").write_text("// renderer")
    (core / "layouts.js").write_text("// layouts")
    (core / "theme.js").write_text("// theme")
    (core / "markdown.js").write_text("// markdown")
    (core / "style.css").write_text("body {}")
    vendor = core / "vendor"
    vendor.mkdir()
    (vendor / "markdown-it.min.js").write_text("// md")

    fonts_dir = tmp_path / "shapes" / "deck" / "fonts" / "inter"
    fonts_dir.mkdir(parents=True)
    (fonts_dir / "Inter-Variable.woff2").write_bytes(b"fakefont")

    themes_dir = tmp_path / "shapes" / "deck" / "themes" / "default"
    themes_dir.mkdir(parents=True)
    (themes_dir / "tokens.yaml").write_text(yaml.dump({"colors": {"primary": "#000"}}))
    (themes_dir / "style.css").write_text("[data-theme=default] {}")

    (tmp_path / "shapes" / "deck" / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "deck", "type": "renderer", "version": "0.4.0"
    }))

    content_dir = tmp_path / "content" / "example"
    content_dir.mkdir(parents=True)
    content_file = content_dir / "test-deck.yaml"
    content_file.write_text(yaml.dump({
        "instance": "deck", "shape": "deck", "version": "0.4.0",
        "schema": "deck.v1.json", "theme": "default",
        "title": "Test Deck",
        "slides": [{"id": "intro", "layout": "cover", "content": {"heading": "Hello"}}]
    }))

    return content_file


def test_plain_build_produces_expected_files(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    build_dir, _ = build(content_file, "deck", tmp_path)

    assert build_dir.exists()
    assert (build_dir / "index.html").exists()
    assert (build_dir / "app.js").exists()
    assert (build_dir / "renderer.js").exists()
    assert (build_dir / "layouts.js").exists()
    assert (build_dir / "theme.js").exists()
    assert (build_dir / "markdown.js").exists()
    assert (build_dir / "style.css").exists()
    assert (build_dir / "vendor" / "markdown-it.min.js").exists()
    assert (build_dir / "fonts" / "inter" / "Inter-Variable.woff2").exists()
    assert (build_dir / "theme" / "tokens.json").exists()
    assert (build_dir / "theme" / "style.css").exists()


def test_plain_build_content_json_is_valid(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    build_dir, _ = build(content_file, "deck", tmp_path)

    content_json = json.loads((build_dir / "content.json").read_text())
    assert content_json["title"] == "Test Deck"
    assert content_json["slides"][0]["content"]["heading"] == "Hello"
    assert "encrypted" not in content_json


def test_plain_build_theme_tokens_json(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    build_dir, _ = build(content_file, "deck", tmp_path)

    tokens = json.loads((build_dir / "theme" / "tokens.json").read_text())
    assert tokens["colors"]["primary"] == "#000"


def test_plain_build_wipes_previous_build(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    build_dir, _ = build(content_file, "deck", tmp_path)

    stale = build_dir / "stale-leftover.txt"
    stale.write_text("should be gone")

    build_dir, _ = build(content_file, "deck", tmp_path)
    assert not stale.exists()


def test_build_copies_media_to_data_directory(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)

    img_dir = tmp_path / "content" / "example" / "assets"
    img_dir.mkdir(parents=True)
    (img_dir / "diagram.png").write_bytes(b"PNG fake")

    content_file.write_text(yaml.dump({
        "instance": "deck", "shape": "deck", "version": "0.4.0",
        "schema": "deck.v1.json", "theme": "default",
        "title": "Test",
        "slides": [{
            "id": "s1", "layout": "full",
            "content": {"heading": "X", "media": "content/example/assets/diagram.png"}
        }]
    }))

    build_dir, _ = build(content_file, "deck", tmp_path)
    copied = build_dir / "data" / "content" / "example" / "assets" / "diagram.png"
    assert copied.exists()
    assert copied.read_bytes() == b"PNG fake"


def test_build_copies_artifact_html(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)

    artifact_dir = tmp_path / "content" / "artifacts"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "chart.html").write_text("<div>chart</div>")

    content_file.write_text(yaml.dump({
        "instance": "deck", "shape": "deck", "version": "0.4.0",
        "schema": "deck.v1.json", "theme": "default",
        "title": "Test",
        "slides": [{
            "id": "s1", "layout": "split",
            "left": {"content": {"heading": "Left"}},
            "right": {"content": {"media": "content/artifacts/chart.html"}}
        }]
    }))

    build_dir, _ = build(content_file, "deck", tmp_path)
    copied = build_dir / "data" / "content" / "artifacts" / "chart.html"
    assert copied.exists()



def test_encrypted_build_produces_encrypted_envelope(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    build_dir, mnemonic = build(content_file, "deck", tmp_path, encrypted=True)

    envelope = json.loads((build_dir / "content.json").read_text())
    assert envelope["encrypted"] is True
    assert "salt" in envelope
    assert "iv" in envelope
    assert "payload" in envelope
    assert envelope["meta"]["title"] == "Test Deck"

    salt_bytes = base64.b64decode(envelope["salt"])
    assert len(salt_bytes) == 16

    iv_bytes = base64.b64decode(envelope["iv"])
    assert len(iv_bytes) == 12


def test_encrypted_build_returns_mnemonic(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    build_dir, mnemonic = build(content_file, "deck", tmp_path, encrypted=True)
    assert mnemonic is not None
    assert len(mnemonic.split()) >= 6


def test_encrypted_build_reuses_mnemonic_when_passed(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    _, mnemonic_1 = build(content_file, "deck", tmp_path, encrypted=True)
    _, mnemonic_2 = build(content_file, "deck", tmp_path, encrypted=True, mnemonic=mnemonic_1)
    assert mnemonic_1 == mnemonic_2


def test_encrypted_build_rotates_mnemonic(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    _, mnemonic_1 = build(content_file, "deck", tmp_path, encrypted=True)
    _, mnemonic_2 = build(content_file, "deck", tmp_path, encrypted=True, mnemonic=mnemonic_1, rotate=True)
    assert mnemonic_1 != mnemonic_2


def test_encrypted_build_theme_is_not_encrypted(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    build_dir, _ = build(content_file, "deck", tmp_path, encrypted=True)

    tokens = json.loads((build_dir / "theme" / "tokens.json").read_text())
    assert tokens["colors"]["primary"] == "#000"
    assert (build_dir / "theme" / "style.css").read_text() == "[data-theme=default] {}"


def test_end_to_end_plain_build_is_serveable(tmp_path):
    """A plain build produces a directory a browser can open."""
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    build_dir, _ = build(content_file, "deck", tmp_path)

    index = (build_dir / "index.html").read_text()
    assert "<html" in index

    content = json.loads((build_dir / "content.json").read_text())
    assert "slides" in content

    tokens = json.loads((build_dir / "theme" / "tokens.json").read_text())
    assert isinstance(tokens, dict)

    assert (build_dir / "app.js").exists()
    assert (build_dir / "renderer.js").exists()
    assert (build_dir / "style.css").exists()


def test_build_bundles_component_files(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)

    # Create a component at corpus root
    comp_dir = tmp_path / "components" / "stat-card"
    comp_dir.mkdir(parents=True)
    (comp_dir / "component.yaml").write_text(yaml.dump({
        "name": "stat-card", "fields": {"stat": {"type": "string"}}
    }))
    (comp_dir / "render.js").write_text("export function render(data, theme) { return document.createDocumentFragment(); }")
    (comp_dir / "style.css").write_text("[data-component='stat-card'] { font-size: 2rem; }")

    # Update content to reference the component
    content_file.write_text(yaml.dump({
        "instance": "deck", "shape": "deck", "version": "0.4.0",
        "schema": "deck.v1.json", "theme": "default",
        "title": "Test",
        "slides": [{"layout": "grid", "cells": [
            {"content": {"component": "stat-card", "data": {"stat": "10%"}}}
        ]}]
    }))

    build_dir, _ = build(content_file, "deck", tmp_path)

    assert (build_dir / "components" / "stat-card" / "render.js").exists()
    assert (build_dir / "components" / "stat-card" / "style.css").exists()


def test_build_skips_components_when_none_referenced(tmp_path):
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    build_dir, _ = build(content_file, "deck", tmp_path)

    assert not (build_dir / "components").exists()


def test_end_to_end_encrypted_build_roundtrip(tmp_path):
    """An encrypted build can be decrypted with the returned mnemonic."""
    from shapes.deck.exporters.build import build

    content_file = _make_corpus(tmp_path)
    build_dir, mnemonic = build(content_file, "deck", tmp_path, encrypted=True)

    envelope = json.loads((build_dir / "content.json").read_text())
    assert envelope["encrypted"] is True

    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = base64.b64decode(envelope["salt"])
    iv = base64.b64decode(envelope["iv"])
    payload = base64.b64decode(envelope["payload"])

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    key = kdf.derive(mnemonic.encode())
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, payload, None)
    decrypted = json.loads(plaintext)

    assert decrypted["title"] == "Test Deck"
    assert decrypted["slides"][0]["content"]["heading"] == "Hello"
