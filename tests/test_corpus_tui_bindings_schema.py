# tests/test_corpus_tui_bindings_schema.py
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

_DIR = Path(__file__).parent.parent / "shapes/corpus/renderer/tui"
_SCHEMA = json.loads((_DIR / "bindings.v1.json").read_text())


def test_default_keymap_validates():
    doc = yaml.safe_load((_DIR / "bindings.default.yaml").read_text())
    for binding in doc["bindings"]:
        jsonschema.validate(binding, _SCHEMA)


def test_binding_requires_capability_key_label():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"key": "x", "label": "x"}, _SCHEMA)  # no capability


def test_key_must_be_single_char():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"capability": "lens", "key": "ff", "label": "f"}, _SCHEMA)


def test_extra_keys_rejected():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"capability": "lens", "key": "1", "label": "all", "x": 1}, _SCHEMA)


def test_default_keymap_binds_the_read_slice_capabilities():
    doc = yaml.safe_load((_DIR / "bindings.default.yaml").read_text())
    caps = {b["capability"] for b in doc["bindings"]}
    assert {"lens", "filter", "open-artifact"} <= caps
