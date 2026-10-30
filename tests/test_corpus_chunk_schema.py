# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import json
from pathlib import Path

import jsonschema
import pytest

_SCHEMA = json.loads(
    (Path(__file__).parent.parent
     / "shapes/corpus/schemas/chunk.v1.json").read_text())


def test_valid_record_passes():
    rec = {"ref": "c1a2b3c4d", "ast_path": "wohnsituation > mietvertrag",
           "span": [8412, 8909], "contiguous": True, "text": "…befristet? Ja…"}
    jsonschema.validate(rec, _SCHEMA)


def test_sequential_int_ref_rejected():
    rec = {"ref": 0, "ast_path": "x", "span": [0, 1], "contiguous": True, "text": "a"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(rec, _SCHEMA)


def test_span_must_be_two_integers():
    rec = {"ref": "c1a2b3c4d", "ast_path": "x", "span": [5], "contiguous": True, "text": "a"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(rec, _SCHEMA)


def test_ref_pattern_rejects_wrong_format_strings():
    """A right-type (string) but wrong-format ref must fail the pattern — an
    int fails on type before the pattern runs, so it does not prove this."""
    for bad in ("c1a2b3c", "c1A2B3C4D", "x1a2b3c4d", "1a2b3c4d"):
        rec = {"ref": bad, "ast_path": "x", "span": [0, 1], "contiguous": True,
               "text": "a"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(rec, _SCHEMA)


def test_extra_keys_rejected():
    rec = {"ref": "c1a2b3c4d", "ast_path": "x", "span": [0, 1], "contiguous": True,
           "text": "a", "size": 1}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(rec, _SCHEMA)
