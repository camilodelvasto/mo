import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA = json.loads(Path("shapes/corpus/schemas/ask.v1.json").read_text())

def _doc(ask_extra):
    return {"id": "x", "version": 1,
            "asks": [{"id": "read", **ask_extra}]}

def test_ask_accepts_attachments_block():
    jsonschema.validate(_doc({"attachments": {
        "accept": ["image"], "max_count": 3, "max_bytes": 10485760}}), SCHEMA)

def test_bad_accept_enum_is_rejected():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_doc({"attachments": {"accept": ["video"]}}), SCHEMA)

def test_unknown_attachment_key_is_rejected():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_doc({"attachments": {"accept": ["image"], "nope": 1}}), SCHEMA)

def test_attachments_requires_accept():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_doc({"attachments": {"max_count": 3}}), SCHEMA)

def test_content_and_engine_schemas_match():
    if not Path("content/schema/ask.v1.json").is_file():
        pytest.skip("content deposits not present (gitignored, present only on a working checkout)")
    a = json.loads(Path("shapes/corpus/schemas/ask.v1.json").read_text())
    b = json.loads(Path("content/schema/ask.v1.json").read_text())
    assert a["properties"]["asks"]["items"]["properties"]["attachments"] == \
           b["properties"]["asks"]["items"]["properties"]["attachments"]
