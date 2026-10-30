# tests/test_corpus_flow_schema.py
import json
from pathlib import Path

import jsonschema
import pytest

_SCHEMA = json.loads(
    (Path(__file__).parent.parent
     / "shapes/corpus/schemas/flow.v1.json").read_text())

_BASE = {"id": "t", "version": 1,
         "entrypoints": [{"id": "g", "area": "dropbox/general"}],
         "pipeline": [{"id": "stamp", "uses": "engine.stamp"}]}


def _flow(field_decl):
    return {**_BASE, "fields": {"doc_type": field_decl}}


def test_by_string_still_valid():
    jsonschema.validate(_flow({"type": "string", "by": "model"}), _SCHEMA)


def test_by_array_of_both_writers_valid():
    jsonschema.validate(
        _flow({"type": "enum", "values": ["interview"],
               "by": ["model", "operator"]}), _SCHEMA)


def test_by_array_with_bad_member_rejected():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_flow({"type": "string", "by": ["model", "robot"]}),
                            _SCHEMA)
