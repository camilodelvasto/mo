# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from cli.infra.origin import origin_of


def test_origin_strips_path_and_trailing_slash():
    assert origin_of("https://ask.moui.co/api") == "https://ask.moui.co"
    assert origin_of("https://x.github.io/repo/sub/") == "https://x.github.io"


def test_origin_drops_default_port_lowercases_host():
    assert origin_of("https://ASK.moui.co:443/api") == "https://ask.moui.co"
    assert origin_of("http://Example.com:80") == "http://example.com"


def test_origin_keeps_nondefault_port():
    assert origin_of("http://127.0.0.1:8787/x") == "http://127.0.0.1:8787"


def test_origin_idempotent_and_byte_exact_pair():
    # the two strings a human reads as "same origin" must canonicalize identically
    assert origin_of("https://ask.moui.co") == origin_of("https://ask.moui.co:443/")


def test_origin_rejects_no_host():
    with pytest.raises(ValueError):
        origin_of("/api/ask")
