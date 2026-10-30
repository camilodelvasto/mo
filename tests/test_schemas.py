"""Validate that base schemas are valid JSON Schema and that moui.json validates."""
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).parent.parent


def load_json(path):
    return json.loads(path.read_text())


def test_manifest_schema_is_valid_json_schema():
    schema = load_json(ROOT / "schema" / "manifest.v1.json")
    jsonschema.Draft7Validator.check_schema(schema)


def test_bite_schema_is_valid_json_schema():
    schema = load_json(ROOT / "schema" / "bite.v1.json")
    jsonschema.Draft7Validator.check_schema(schema)


def test_shape_schema_is_valid_json_schema():
    schema = load_json(ROOT / "schema" / "shape.v1.json")
    jsonschema.Draft7Validator.check_schema(schema)



def test_moui_json_validates_against_manifest_schema():
    schema = load_json(ROOT / "schema" / "manifest.v1.json")
    instance = load_json(ROOT / "moui.json")
    jsonschema.validate(instance, schema)


def test_moui_json_has_required_fields():
    instance = load_json(ROOT / "moui.json")
    assert instance["v"] == 1
    assert isinstance(instance["name"], str)
    assert isinstance(instance["shapes"], dict)
    for name, shape in instance["shapes"].items():
        assert "shape" in shape
        assert "version" in shape
        assert "local" in shape


def test_bite_schema_deposited_to_content():
    base = load_json(ROOT / "schema" / "bite.v1.json")
    deposited = load_json(ROOT / "content" / "schema" / "bite.v1.json")
    assert base == deposited


def test_slide_schema_deposited_to_content():
    source = load_json(ROOT / "shapes" / "deck" / "schemas" / "slide.v1.json")
    deposited = load_json(ROOT / "content" / "schema" / "slide.v1.json")
    assert source == deposited


def test_moui_json_rejects_invalid():
    schema = load_json(ROOT / "schema" / "manifest.v1.json")
    invalid = {"v": 1, "name": "test"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)


def test_sample_instances_exist_in_moui_json():
    import yaml
    corpus = load_json(ROOT / "moui.json")
    installed = set(corpus["shapes"].keys())
    for path in (ROOT / "content").rglob("*.yaml"):
        if path.parent.name == "schema":
            continue
        data = yaml.safe_load(path.read_text())
        if isinstance(data, dict) and "instance" in data:
            assert data["instance"] in installed, \
                f"{path}: instance '{data['instance']}' not in moui.json"


def test_sample_schema_references_resolve():
    import yaml
    schema_dir = ROOT / "content" / "schema"
    for path in (ROOT / "content").rglob("*.yaml"):
        if path.parent.name == "schema":
            continue
        data = yaml.safe_load(path.read_text())
        if isinstance(data, dict) and "schema" in data:
            assert (schema_dir / data["schema"]).exists(), \
                f"{path}: schema '{data['schema']}' not in content/schema/"


def test_slide_schema_allows_component_in_content_block():
    """contentBlock should accept component + data fields."""
    import json
    import jsonschema

    schema_path = Path(__file__).parent.parent / "content" / "schema" / "slide.v1.json"
    schema = json.loads(schema_path.read_text())

    slide = {
        "layout": "grid",
        "cells": [{
            "content": {
                "component": "stat-card",
                "data": {"stat": "60.6%", "label": "Test", "bar": 60.6}
            }
        }]
    }
    jsonschema.validate(slide, schema)


def test_slide_schema_rejects_invalid_component_name():
    """component must be lowercase kebab-case."""
    import json
    import jsonschema

    schema_path = Path(__file__).parent.parent / "content" / "schema" / "slide.v1.json"
    schema = json.loads(schema_path.read_text())

    slide = {
        "layout": "grid",
        "cells": [{
            "content": {
                "component": "StatCard",
                "data": {}
            }
        }]
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(slide, schema)


def test_slide_schema_accepts_split_stack_layout():
    schema = load_json(ROOT / "shapes" / "deck" / "schemas" / "slide.v1.json")
    slide = {
        "layout": "split-stack",
        "left": {
            "content": {"heading": "Single panel"}
        },
        "right": {
            "panels": [
                {"content": {"heading": "Top"}},
                {"content": {"quote": "Bottom", "attribution": "Someone"}}
            ]
        }
    }
    jsonschema.validate(slide, schema)


def test_slide_schema_accepts_panels_on_both_sides():
    schema = load_json(ROOT / "shapes" / "deck" / "schemas" / "slide.v1.json")
    slide = {
        "layout": "split-stack",
        "left": {
            "panels": [
                {"content": {"heading": "L1"}},
                {"content": {"heading": "L2"}}
            ]
        },
        "right": {
            "panels": [
                {"content": {"media": "img/a.png"}},
                {"content": {"media": "img/b.png"}},
                {"content": {"media": "img/c.png"}}
            ]
        }
    }
    jsonschema.validate(slide, schema)


def test_slide_schema_rejects_panels_with_zero_items():
    schema = load_json(ROOT / "shapes" / "deck" / "schemas" / "slide.v1.json")
    slide = {
        "layout": "split-stack",
        "left": {"panels": []},
        "right": {"content": {"heading": "Hello"}}
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(slide, schema)


def test_slide_schema_accepts_string_divider():
    schema = load_json(ROOT / "shapes" / "deck" / "schemas" / "slide.v1.json")
    slide = {
        "layout": "split",
        "left": {"content": {"heading": "A"}},
        "right": {"content": {"heading": "B"}},
        "style": {"divider": "accent-coral", "ratio": "50/50"}
    }
    jsonschema.validate(slide, schema)


def test_slide_schema_rejects_boolean_divider():
    schema = load_json(ROOT / "shapes" / "deck" / "schemas" / "slide.v1.json")
    slide = {
        "layout": "split",
        "left": {"content": {"heading": "A"}},
        "right": {"content": {"heading": "B"}},
        "style": {"divider": False}
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(slide, schema)


def test_manifest_accepts_inference_block(tmp_path):
    """Manifest schema must allow an inference configuration block."""
    import json, jsonschema
    schema_path = Path(__file__).resolve().parent.parent / "schema" / "manifest.v1.json"
    schema = json.loads(schema_path.read_text())
    instance = {
        "v": 1,
        "name": "test",
        "shapes": {
            "sheets": {"shape": "sheets", "version": "0.1.0", "local": True}
        },
        "inference": {
            "default": {"backend": "ollama", "model": "qwen3:8b"}
        },
    }
    jsonschema.validate(instance, schema)  # must not raise


def test_shape_schema_accepts_custom_capabilities():
    """Shape schema must allow shape-specific capabilities with adapter fields."""
    import json, jsonschema
    schema_path = Path(__file__).resolve().parent.parent / "schema" / "shape.v1.json"
    schema = json.loads(schema_path.read_text())
    instance = {
        "name": "sheets",
        "version": "0.1.0",
        "type": "service",
        "description": "Structured data shape",
        "capabilities": {
            "serve": [{"adapter": "commands/serve.py"}],
            "tui": [{"adapter": "commands/tui.py"}],
        },
        "schemas": {
            "extends": [],
            "defines": ["sheet.v1.json", "ops.v1.json"],
            "deposits_to": "content/schema/",
        },
        "permissions": {
            "filesystem": {
                "read": ["content/"],
                "write": ["shapes/sheets/.rendered/", ".corpus/shapes/sheets/"],
            },
            "network": "local",
            "subprocess": "none",
        },
    }
    jsonschema.validate(instance, schema)  # must not raise
