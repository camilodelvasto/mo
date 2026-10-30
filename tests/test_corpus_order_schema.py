# tests/test_corpus_order_schema.py
import json
from pathlib import Path

import jsonschema
import pytest

_SCHEMA = json.loads(
    (Path(__file__).parent.parent
     / "shapes/corpus/schemas/order.v1.json").read_text())


def test_retire_order_valid():
    jsonschema.validate({"doc_id": "aaaaaaaaaaaa", "by": "operator",
                         "action": "retire"}, _SCHEMA)


def test_reprocess_order_valid_with_from():
    jsonschema.validate({"doc_id": "aaaaaaaaaaaa", "by": "operator",
                         "action": "reprocess", "from": "datasheet"}, _SCHEMA)


def test_unknown_action_rejected():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"doc_id": "aaaaaaaaaaaa", "by": "operator",
                             "action": "delete"}, _SCHEMA)
