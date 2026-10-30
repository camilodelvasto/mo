# tests/test_corpus_queries_schema.py
import json
from pathlib import Path

import jsonschema
import pytest

_SCHEMA = json.loads(
    (Path(__file__).parent.parent
     / "shapes/corpus/schemas/corpus.v1.json").read_text())


def test_queries_is_an_optional_string():
    jsonschema.validate({"id": "c", "flow": "./flow.yaml"}, _SCHEMA)            # absent: ok
    jsonschema.validate({"id": "c", "flow": "./flow.yaml",
                         "queries": "./queries"}, _SCHEMA)                       # present: ok


def test_queries_rejects_non_string():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"id": "c", "flow": "./flow.yaml", "queries": 7}, _SCHEMA)
