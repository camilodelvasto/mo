"""Test moui check — the corpus validation command."""
import json
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent


def test_check_passes_on_valid_corpus():
    from cli.check import run_check
    result = run_check(ROOT, [])
    assert result == 0


def test_check_validates_moui_json_against_schema():
    from cli.check import validate_corpus_manifest
    errors = validate_corpus_manifest(ROOT)
    assert errors == []


def test_check_validates_each_shape_manifest():
    from cli.check import validate_shape_manifests
    errors = validate_shape_manifests(ROOT)
    assert errors == []


def test_check_validates_schema_deposits():
    from cli.check import validate_schema_deposits
    errors = validate_schema_deposits(ROOT)
    assert errors == []


def test_check_validates_content_metadata():
    from cli.check import validate_content_metadata
    errors = validate_content_metadata(ROOT)
    assert errors == []


def test_check_catches_invalid_moui_json(tmp_path):
    from cli.check import validate_corpus_manifest
    (tmp_path / "moui.json").write_text(json.dumps({"v": 1, "name": "test"}))
    shutil.copytree(ROOT / "schema", tmp_path / "schema")
    errors = validate_corpus_manifest(tmp_path)
    assert len(errors) > 0


def test_check_catches_missing_schema_deposit(tmp_path):
    from cli.check import validate_schema_deposits
    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test",
        "shapes": {"leaf": {"shape": "leaf", "version": "1.0.0", "local": True}}
    }))
    shape_dir = tmp_path / "shapes" / "leaf"
    shape_dir.mkdir(parents=True)
    shutil.copy(ROOT / "shapes" / "leaf" / "shape.manifest.yaml", shape_dir / "shape.manifest.yaml")
    (tmp_path / "content" / "schema").mkdir(parents=True)
    errors = validate_schema_deposits(tmp_path)
    assert len(errors) > 0


def test_check_catches_missing_schemas_block(tmp_path):
    from cli.check import validate_schema_deposits
    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test",
        "shapes": {"broken": {"shape": "broken", "version": "1.0.0", "local": True}}
    }))
    shape_dir = tmp_path / "shapes" / "broken"
    shape_dir.mkdir(parents=True)
    # Manifest with no schemas block
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "broken", "version": "1.0.0", "type": "renderer",
        "description": "test", "capabilities": {"render": [{"type": "x"}]},
        "permissions": {"filesystem": {"read": [], "write": []}, "network": "none"},
    }))
    errors = validate_schema_deposits(tmp_path)
    assert any("missing 'schemas' block" in e for e in errors)


def test_check_catches_missing_schema_field_in_content(tmp_path):
    from cli.check import validate_content_metadata
    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test",
        "shapes": {"leaf": {"shape": "leaf", "version": "1.0.0", "local": True}}
    }))
    (tmp_path / "shapes" / "leaf").mkdir(parents=True)
    content_dir = tmp_path / "content" / "example"
    content_dir.mkdir(parents=True)
    (tmp_path / "content" / "schema").mkdir(parents=True)
    # Bite with instance but no schema
    (content_dir / "bad.yaml").write_text(yaml.dump({
        "instance": "leaf", "shape": "leaf", "version": "1.0.0",
        "title": "Missing schema field"
    }))
    errors = validate_content_metadata(tmp_path)
    assert any("missing required 'schema' field" in e for e in errors)


def test_check_shape_flag_runs_single_shape():
    from cli.check import run_check
    result = run_check(ROOT, ["--shape", "leaf"])
    assert result == 0


def test_check_shape_flag_rejects_unknown():
    from cli.check import run_check
    result = run_check(ROOT, ["--shape", "nonexistent"])
    assert result != 0


def test_check_fast_skips_content_metadata():
    from cli.check import run_check
    result = run_check(ROOT, ["--fast"])
    assert result == 0


def test_check_catches_missing_component(tmp_path):
    from cli.check import validate_components

    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test",
        "shapes": {"deck": {"shape": "deck", "version": "0.4.0", "local": True}}
    }))
    shape_dir = tmp_path / "shapes" / "deck"
    shape_dir.mkdir(parents=True)
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "deck", "type": "renderer", "version": "0.4.0",
        "description": "test", "capabilities": {"render": [{"type": "deck"}]},
        "permissions": {"filesystem": {"read": [], "write": []}, "network": "none"},
        "schemas": {"defines": ["deck.v1.json", "slide.v1.json"]},
    }))

    content_dir = tmp_path / "content" / "example"
    content_dir.mkdir(parents=True)
    (tmp_path / "content" / "schema").mkdir(parents=True)
    content_file = content_dir / "test.yaml"
    content_file.write_text(yaml.dump({
        "instance": "deck", "shape": "deck", "version": "0.4.0",
        "schema": "deck.v1.json", "theme": "default",
        "title": "Test",
        "slides": [{"layout": "grid", "cells": [
            {"content": {"component": "stat-card", "data": {"stat": "10%"}}}
        ]}]
    }))

    errors = validate_components(tmp_path)
    assert any("stat-card" in e and "not found" in e for e in errors)


def test_check_catches_missing_theme_dependency(tmp_path):
    from cli.check import validate_components

    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test",
        "shapes": {"deck": {"shape": "deck", "version": "0.4.0", "local": True}}
    }))
    shape_dir = tmp_path / "shapes" / "deck"
    shape_dir.mkdir(parents=True)
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "deck", "type": "renderer", "version": "0.4.0",
        "description": "test", "capabilities": {"render": [{"type": "deck"}]},
        "permissions": {"filesystem": {"read": [], "write": []}, "network": "none"},
        "schemas": {"defines": ["deck.v1.json", "slide.v1.json"]},
    }))

    # Component exists with theme-requires
    comp_dir = tmp_path / "components" / "stat-card"
    comp_dir.mkdir(parents=True)
    (comp_dir / "component.yaml").write_text(yaml.dump({
        "name": "stat-card",
        "theme-requires": ["bar-gradient-from", "bar-gradient-to"],
        "fields": {"stat": {"type": "string"}}
    }))

    # Theme exists but lacks the required tokens
    theme_dir = shape_dir / "themes" / "default"
    theme_dir.mkdir(parents=True)
    (theme_dir / "tokens.yaml").write_text(yaml.dump({
        "palette": {"accent": "#000"},
        "reveal": {"type": "fade", "stagger": True, "speed": 1.0}
    }))
    (theme_dir / "style.css").write_text("")

    content_dir = tmp_path / "content" / "example"
    content_dir.mkdir(parents=True)
    (tmp_path / "content" / "schema").mkdir(parents=True)
    content_file = content_dir / "test.yaml"
    content_file.write_text(yaml.dump({
        "instance": "deck", "shape": "deck", "version": "0.4.0",
        "schema": "deck.v1.json", "theme": "default",
        "title": "Test",
        "slides": [{"layout": "grid", "cells": [
            {"content": {"component": "stat-card", "data": {"stat": "10%"}}}
        ]}]
    }))

    errors = validate_components(tmp_path)
    assert any("bar-gradient-from" in e for e in errors)


def test_check_passes_when_component_and_theme_valid(tmp_path):
    from cli.check import validate_components

    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test",
        "shapes": {"deck": {"shape": "deck", "version": "0.4.0", "local": True}}
    }))
    shape_dir = tmp_path / "shapes" / "deck"
    shape_dir.mkdir(parents=True)
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "deck", "type": "renderer", "version": "0.4.0",
        "description": "test", "capabilities": {"render": [{"type": "deck"}]},
        "permissions": {"filesystem": {"read": [], "write": []}, "network": "none"},
        "schemas": {"defines": ["deck.v1.json", "slide.v1.json"]},
    }))

    comp_dir = tmp_path / "components" / "stat-card"
    comp_dir.mkdir(parents=True)
    (comp_dir / "component.yaml").write_text(yaml.dump({
        "name": "stat-card",
        "theme-requires": ["bar-gradient-from"],
        "fields": {"stat": {"type": "string"}}
    }))

    theme_dir = shape_dir / "themes" / "default"
    theme_dir.mkdir(parents=True)
    (theme_dir / "tokens.yaml").write_text(yaml.dump({
        "palette": {"accent": "#000"},
        "bar-gradient-from": "accent",
        "reveal": {"type": "fade", "stagger": True, "speed": 1.0}
    }))
    (theme_dir / "style.css").write_text("")

    content_dir = tmp_path / "content" / "example"
    content_dir.mkdir(parents=True)
    (tmp_path / "content" / "schema").mkdir(parents=True)
    content_file = content_dir / "test.yaml"
    content_file.write_text(yaml.dump({
        "instance": "deck", "shape": "deck", "version": "0.4.0",
        "schema": "deck.v1.json", "theme": "default",
        "title": "Test",
        "slides": [{"layout": "grid", "cells": [
            {"content": {"component": "stat-card", "data": {"stat": "10%"}}}
        ]}]
    }))

    errors = validate_components(tmp_path)
    assert errors == []


def test_check_catches_token_collision():
    from cli.check import validate_token_collisions
    tokens = {
        "palette": {"accent": "#06b6d4"},
        "gradients": {"accent": "linear-gradient(90deg, #06b6d4, #f97316)"},
        "borders": {}
    }
    errors = validate_token_collisions(tokens, "test-theme")
    assert len(errors) > 0
    assert any("accent" in e for e in errors)


def test_check_passes_with_no_token_collisions():
    from cli.check import validate_token_collisions
    tokens = {
        "palette": {"accent": "#06b6d4"},
        "gradients": {"sunset": "linear-gradient(90deg, #fbbf24, #ef4444)"},
        "borders": {"thin": "1px solid"}
    }
    errors = validate_token_collisions(tokens, "test-theme")
    assert errors == []


def _make_grove_corpus(tmp_path: Path, feature_id_in_page: str) -> None:
    """Build a minimal corpus with one grove that declares a feature as a list."""
    # page.v1.json schema deposit
    schema_dir = tmp_path / "content" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "page.v1.json").write_text(json.dumps({
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "page.v1.json",
        "title": "Moui Grove Page",
        "type": "object",
        "required": ["title"],
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "body": {"type": "array"},
        },
    }))
    # grove root with features declared as a list
    grove_dir = tmp_path / "content" / "mygrove"
    grove_dir.mkdir(parents=True)
    (grove_dir / "grove.yaml").write_text(yaml.dump({
        "title": "Test Grove",
        "features": [
            {"id": "assistant", "type": "chat", "ask": "faq"},
        ],
        "pages": {"/chatbot": "pages/chatbot"},
    }))
    # page folder referenced by the pages map
    page_dir = grove_dir / "pages" / "chatbot"
    page_dir.mkdir(parents=True)
    (page_dir / "page.yaml").write_text(yaml.dump({
        "title": "Chatbot",
        "body": [{"feature": feature_id_in_page}],
    }))


def test_grove_pages_declared_feature_passes(tmp_path):
    """A {feature: assistant} ref to a declared feature produces no errors."""
    from cli.check import validate_grove_pages
    _make_grove_corpus(tmp_path, feature_id_in_page="assistant")
    errors = validate_grove_pages(tmp_path)
    assert errors == []


def test_grove_pages_undeclared_feature_raises_error(tmp_path):
    """A {feature: nope} ref to an undeclared feature is reported with the route."""
    from cli.check import validate_grove_pages
    _make_grove_corpus(tmp_path, feature_id_in_page="nope")
    errors = validate_grove_pages(tmp_path)
    assert len(errors) == 1
    assert "/chatbot" in errors[0]
    assert "nope" in errors[0]
