from pathlib import Path

import yaml

SHAPE = Path(__file__).resolve().parents[1] / "shapes" / "corpus"


def test_preview_ask_validates_against_schema():
    import json, jsonschema, yaml
    schema = json.loads((SHAPE / "schemas" / "ask.v1.json").read_text())
    ask = yaml.safe_load((SHAPE / "preview/corpus-example/ask.yaml").read_text())
    jsonschema.validate(ask, schema)  # raises on a malformed preview


def test_manifest_declares_access_verbs():
    manifest = yaml.safe_load((SHAPE / "shape.manifest.yaml").read_text())
    caps = manifest["capabilities"]
    for verb, adapter in [("index", "commands/index_cmd.py"),
                          ("find", "commands/find.py"),
                          ("ask", "commands/ask.py")]:
        assert verb in caps, f"manifest missing {verb}"
        assert caps[verb][0]["adapter"] == adapter
        assert (SHAPE / adapter).is_file(), f"adapter file missing: {adapter}"


def test_parse_query_args_grounding_valid():
    from shapes.corpus.commands._access_cli import parse_query_args
    q, opts = parse_query_args(["¿qué?", "--grounding", "0.7"])
    assert q == "¿qué?" and opts["grounding"] == 0.7


def test_parse_query_args_grounding_absent():
    from shapes.corpus.commands._access_cli import parse_query_args
    q, opts = parse_query_args(["¿qué?"])
    assert "grounding" not in opts          # absent → caller applies the default


def test_parse_query_args_grounding_out_of_range_raises():
    import pytest
    from shapes.corpus.commands._access_cli import parse_query_args
    for bad in ("1.5", "-0.2", "high"):
        with pytest.raises(SystemExit):
            parse_query_args(["¿qué?", "--grounding", bad])


def test_ask_schema_allows_grounding_override():
    import json, jsonschema, pytest
    schema = json.loads((SHAPE / "schemas" / "ask.v1.json").read_text())
    ok = {"id": "a", "version": 1, "asks": [
        {"id": "x", "grounding": "lvl ${grounding}", "synthesize": {"uses": "api.claude", "prompt": "p"}}]}
    jsonschema.validate(ok, schema)
    bad = {"id": "a", "version": 1, "asks": [{"id": "x", "bogus": 1}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)   # contract stays closed


def test_parse_query_args_json_flag():
    from shapes.corpus.commands._access_cli import parse_query_args
    q, opts = parse_query_args(["¿qué?", "--json"])
    assert q == "¿qué?" and opts["json"] is True


def test_parse_query_args_json_absent():
    from shapes.corpus.commands._access_cli import parse_query_args
    q, opts = parse_query_args(["¿qué?"])
    assert "json" not in opts


def test_parse_grounding_valid_and_invalid():
    import pytest
    from shapes.corpus.commands._access_cli import parse_grounding
    assert parse_grounding("0.7") == 0.7
    for bad in ("1.5", "-0.2", "high"):
        with pytest.raises(SystemExit):
            parse_grounding(bad)
