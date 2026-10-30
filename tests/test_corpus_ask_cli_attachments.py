# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import json
from shapes.corpus.commands import _access_cli


def test_attachments_file_is_parsed(tmp_path):
    p = tmp_path / "atts.json"
    p.write_text(json.dumps([{"data": "AA==", "signature": "s", "media_type": "image/webp"}]))
    _q, opts = _access_cli.parse_query_args(["q", "--attachments", f"@{p}"])
    assert opts["attachments"][0]["media_type"] == "image/webp"


def test_attachments_inline_json_is_parsed():
    _q, opts = _access_cli.parse_query_args(
        ["q", "--attachments", json.dumps([{"data": "AA==", "signature": "s", "media_type": "image/webp"}])])
    assert opts["attachments"][0]["signature"] == "s"


def test_attachments_bad_json_throws():
    import pytest
    with pytest.raises(SystemExit):
        _access_cli.parse_query_args(["q", "--attachments", "{not json"])
