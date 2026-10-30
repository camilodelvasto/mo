"""Validate shape manifests, schema deposits, and structural contracts."""
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).parent.parent


def load_json(path):
    return json.loads(path.read_text())


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def test_leaf_manifest_validates():
    schema = load_json(ROOT / "schema" / "shape.v1.json")
    manifest = load_yaml(ROOT / "shapes" / "leaf" / "shape.manifest.yaml")
    jsonschema.validate(manifest, schema)


def test_deck_manifest_validates():
    schema = load_json(ROOT / "schema" / "shape.v1.json")
    manifest = load_yaml(ROOT / "shapes" / "deck" / "shape.manifest.yaml")
    jsonschema.validate(manifest, schema)



def test_leaf_schema_deposits_exist():
    manifest = load_yaml(ROOT / "shapes" / "leaf" / "shape.manifest.yaml")
    for schema_name in manifest["schemas"]["defines"]:
        path = ROOT / "content" / "schema" / schema_name
        assert path.exists(), f"Missing deposited schema: {path}"


def test_deck_schema_deposits_exist():
    manifest = load_yaml(ROOT / "shapes" / "deck" / "shape.manifest.yaml")
    for schema_name in manifest["schemas"]["defines"]:
        path = ROOT / "content" / "schema" / schema_name
        assert path.exists(), f"Missing deposited schema: {path}"


def test_leaf_themes_exist():
    default = ROOT / "shapes" / "leaf" / "themes" / "default" / "tokens.yaml"
    dark = ROOT / "shapes" / "leaf" / "themes" / "dark" / "tokens.yaml"
    assert default.exists()
    assert dark.exists()


def test_deck_themes_exist():
    for name in ["default", "personal", "business", "sensata"]:
        tokens = ROOT / "shapes" / "deck" / "themes" / name / "tokens.yaml"
        assert tokens.exists(), f"Missing deck theme tokens: {tokens}"


def test_leaf_preview_has_valid_metadata():
    preview_path = ROOT / "shapes" / "leaf" / "preview" / "post-example.md"
    text = preview_path.read_text()
    parts = text.split("---", 2)
    assert len(parts) >= 3, "Markdown preview must have frontmatter"
    metadata = yaml.safe_load(parts[1])
    assert metadata["instance"] == "leaf"
    assert metadata["schema"] == "post.v1.json"


def test_deck_preview_has_valid_metadata():
    preview = load_yaml(ROOT / "shapes" / "deck" / "preview" / "deck-example.yaml")
    assert preview["instance"] == "deck"
    assert preview["schema"] == "deck.v1.json"
    assert len(preview["slides"]) >= 1


def test_each_shape_in_moui_json_has_manifest():
    moui = load_json(ROOT / "moui.json")
    for instance_name, shape_info in moui["shapes"].items():
        manifest_path = ROOT / "shapes" / instance_name / "shape.manifest.yaml"
        assert manifest_path.exists(), f"Missing manifest for {instance_name}: {manifest_path}"


def test_grove_themes_exist():
    for name in ["default", "dark"]:
        theme_dir = ROOT / "shapes" / "grove" / "themes" / name
        assert theme_dir.is_dir(), f"Missing grove theme directory: {theme_dir}"
        assert (theme_dir / "tokens.yaml").exists(), f"Missing tokens.yaml in {theme_dir}"


PROTO = ROOT


def test_manifest_with_import_map_validates():
    """A manifest with import_map in dependencies.python should pass schema validation."""
    schema = json.loads((PROTO / "schema" / "shape.v1.json").read_text())
    manifest = {
        "name": "test-shape",
        "version": "1.0.0",
        "type": "renderer",
        "description": "Test shape",
        "capabilities": {"render": [{"type": "test"}]},
        "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
        "permissions": {"filesystem": {"read": [], "write": []}, "network": "none", "subprocess": "none"},
        "dependencies": {
            "python": {
                "core": ["pyyaml>=6.0"],
                "import_map": {"pyyaml": "yaml"}
            }
        }
    }
    jsonschema.validate(manifest, schema)


def test_engine_manifest_validates():
    """shape.v1.json accepts type: engine with builtins: and config:."""
    schema = load_json(ROOT / "schema" / "shape.v1.json")
    manifest = {
        "name": "test-engine",
        "version": "0.1.0",
        "type": "engine",
        "description": "Test engine shape",
        "capabilities": {"watch": [{"adapter": "commands/watch.py"}]},
        "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
        "builtins": ["engine.stamp", "engine.passthrough"],
        "permissions": {
            "filesystem": {"read": ["content/"], "write": ["content/"]},
            "network": "none",
            "subprocess": "restricted",
        },
        "config": {
            "schema": "config/capabilities.schema.json",
            "example": "config/capabilities.example.yaml",
        },
    }
    jsonschema.validate(manifest, schema)

    # Validate that builtins and config are optional
    minimal_manifest = manifest.copy()
    del minimal_manifest["builtins"]
    del minimal_manifest["config"]
    jsonschema.validate(minimal_manifest, schema)


def test_unknown_manifest_property_still_rejected():
    """The contract stays closed: undeclared properties fail validation."""
    schema = load_json(ROOT / "schema" / "shape.v1.json")
    manifest = {
        "name": "x", "version": "0.1.0", "type": "engine", "description": "x",
        "capabilities": {}, "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
        "permissions": {"filesystem": {"read": [], "write": []}, "network": "none", "subprocess": "none"},
        "smuggled": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


def test_corpus_manifest_validates():
    schema = load_json(ROOT / "schema" / "shape.v1.json")
    manifest = load_yaml(ROOT / "shapes" / "corpus" / "shape.manifest.yaml")
    jsonschema.validate(manifest, schema)


def test_corpus_schema_deposits_exist():
    manifest = load_yaml(ROOT / "shapes" / "corpus" / "shape.manifest.yaml")
    for schema_name in manifest["schemas"]["defines"]:
        path = ROOT / "content" / "schema" / schema_name
        assert path.exists(), f"Missing deposited schema: {path}"


def test_corpus_schema_copies_stay_equal():
    """Deposits and the config copy must not drift from their sources."""
    if not (ROOT / "content" / "schema").is_dir():
        pytest.skip("content deposits not present (gitignored, present only on a working checkout)")
    manifest = load_yaml(ROOT / "shapes" / "corpus" / "shape.manifest.yaml")
    for schema_name in manifest["schemas"]["defines"]:
        source = load_json(ROOT / "shapes" / "corpus" / "schemas" / schema_name)
        deposited = load_json(ROOT / "content" / "schema" / schema_name)
        assert source == deposited, f"deposit drifted: {schema_name}"
    cap_source = load_json(ROOT / "shapes" / "corpus" / "schemas" / "capabilities.v1.json")
    cap_config = load_json(ROOT / "shapes" / "corpus" / "config" / "capabilities.schema.json")
    assert cap_source == cap_config, "config/capabilities.schema.json drifted"


def test_corpus_flow_schema_rejects_incomplete_fields():
    schema = load_json(ROOT / "shapes" / "corpus" / "schemas" / "flow.v1.json")
    base = {"id": "t", "version": 1,
            "entrypoints": [{"id": "g", "area": "dropbox/general"}],
            "pipeline": [{"id": "s", "uses": "engine.stamp"}]}
    bad_enum = dict(base, fields={"x": {"type": "enum", "by": "operator"}})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad_enum, schema)
    bad_set = dict(base, fields={"x": {"type": "set", "by": "operator"}})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad_set, schema)


def test_corpus_capabilities_schema_rejects_map_without_exit_code():
    schema = load_json(ROOT / "shapes" / "corpus" / "schemas" / "capabilities.v1.json")
    bad = {"capabilities": {"local.x": {
        "run": ["x"], "reads": "stdin", "emits": "stdout",
        "map": {"0": "ok"}}}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_corpus_capabilities_schema_accepts_timeout():
    schema = load_json(ROOT / "shapes" / "corpus" / "schemas" / "capabilities.v1.json")
    ok = {"capabilities": {"local.x": {
        "run": ["x"], "reads": "stdin", "emits": "stdout", "timeout": 60}}}
    jsonschema.validate(ok, schema)


def test_corpus_schema_allows_optional_ask_pointer():
    """corpus.yaml is the shared anchor: `flow` (prep) + optional `ask` (access
    engine). The prep schema must permit `ask` without it being required, while
    staying a closed contract."""
    schema = load_json(ROOT / "shapes" / "corpus" / "schemas" / "corpus.v1.json")
    jsonschema.validate({"id": "c", "flow": "./flow.yaml", "ask": "./ask.yaml"}, schema)
    jsonschema.validate({"id": "c", "flow": "./flow.yaml"}, schema)  # ask optional
    with pytest.raises(jsonschema.ValidationError):                  # still closed
        jsonschema.validate({"id": "c", "flow": "./flow.yaml", "bogus": 1}, schema)


def test_webapp_manifest_validates():
    schema = load_json(ROOT / "schema" / "shape.v1.json")
    manifest = load_yaml(ROOT / "shapes" / "webapp" / "shape.manifest.yaml")
    jsonschema.validate(manifest, schema)


def test_webapp_schema_deposits_match_the_shape():
    manifest = load_yaml(ROOT / "shapes" / "webapp" / "shape.manifest.yaml")
    for schema_name in manifest["schemas"]["defines"]:
        deposit = ROOT / "content" / "schema" / schema_name
        assert deposit.exists(), f"Missing deposited schema: {deposit}"
        assert load_json(deposit) == load_json(ROOT / "shapes" / "webapp" / "schemas" / schema_name)
