# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Static build: chat-config island injection and one-value-both-sinks guarantee.

Uses a minimal in-memory grove + page rather than the real hub grove:
the full build() copies renderer assets, themes, fonts, and favicons from the
corpus layout — none of that is present in tmp_path. Testing compose_page()
directly is the right scope: it is the actual injection point, and _render_pages
is just a loop that calls it. The BuildError guard is tested by patching build()
with a minimal grove fixture that has no asset dependencies.
"""
import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

# Ensure exporters/ is importable even when running the file directly.
_EXPORTERS = Path(__file__).resolve().parent.parent / "shapes" / "grove" / "exporters"
if str(_EXPORTERS) not in sys.path:
    sys.path.insert(0, str(_EXPORTERS))

from shapes.grove.exporters.compose import compose_page  # noqa: E402
from cli.infra.origin import origin_of  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

GROVE = {
    "id": "test-chat",
    "title": "Test Chat",
    "lang": "en",
    "og": {
        "title": "Test Chat",
        "description": "Minimal chat grove for testing.",
        "image": "assets/og.png",
        "twitter_card": "summary",
    },
    "features": [
        {"type": "chat", "id": "assistant", "ask": "converse", "persist": "local"}
    ],
}

def _page(tmp_path: Path) -> dict:
    """Return a minimal chat page dict (as load_pages() would produce it)."""
    return {
        "title": "Chatbot",
        "route": "/chatbot",
        "folder": tmp_path,
        "layout": "app",
        "width": "full",
        "body": [{"feature": "assistant"}],
        "og": {},
    }


# Module-level alias for fixtures that don't need tmp_path (used in PAGES list).
# Tests that call compose_page() directly must rebuild the page with tmp_path.
PAGE = _page(Path("."))

PAGES = [PAGE]

CTX = {
    "base_url": "https://x.github.io/repo",
    "base_path": "",
    "theme_css": "",
    "fonts_css": "",
    "strings": {},
    "features": GROVE["features"],
    "_grove_root": Path("."),
}

FEATURE_ENDPOINTS = {"assistant": "https://ask.moui.co"}
CHAT_CONFIG = {"endpoint": "https://ask.moui.co/api",
               "gate": {"scheme": "access-code", "check": "https://ask.moui.co/api/check"}}


# ---------------------------------------------------------------------------
# Test 1: chat-config island appears when page mounts a chat feature
# ---------------------------------------------------------------------------

def test_compose_page_emits_chat_config_island(tmp_path):
    """compose_page injects the chat-config island before </head> for a chat page."""
    page = _page(tmp_path)
    html = compose_page(page, GROVE, CTX, grove_root=tmp_path, posts=[],
                        feature_endpoints=FEATURE_ENDPOINTS,
                        chat_config=CHAT_CONFIG, pages=[page])
    m = re.search(r'id="chat-config">(\{.*?\})</script>', html, re.S)
    assert m, "chat-config island not found in composed HTML"
    cfg = json.loads(m.group(1))
    assert cfg["endpoint"] == "https://ask.moui.co/api"
    assert cfg["gate"] == {"scheme": "access-code", "check": "https://ask.moui.co/api/check"}
    assert "code" not in cfg


# ---------------------------------------------------------------------------
# Test 2: one-value → both-sinks: the island endpoint origin matches the CSP
# ---------------------------------------------------------------------------

def test_one_value_both_sinks(tmp_path):
    """The endpoint in the island and the connect-src origin in the CSP agree."""
    page = _page(tmp_path)
    html = compose_page(page, GROVE, CTX, grove_root=tmp_path, posts=[],
                        feature_endpoints=FEATURE_ENDPOINTS,
                        chat_config=CHAT_CONFIG, pages=[page])

    m = re.search(r'id="chat-config">(\{.*?\})</script>', html, re.S)
    cfg = json.loads(m.group(1))
    expected_origin = origin_of(cfg["endpoint"])   # https://ask.moui.co
    assert f"connect-src 'self' {expected_origin}" in html, (
        f"connect-src directive for '{expected_origin}' not found in CSP"
    )


# ---------------------------------------------------------------------------
# Test 2b: island carries gate block, never a code key
# ---------------------------------------------------------------------------

def test_compose_page_emits_gate_not_code(tmp_path):
    page = _page(tmp_path)
    html = compose_page(page, GROVE, CTX, grove_root=tmp_path, posts=[],
                        feature_endpoints=FEATURE_ENDPOINTS,
                        chat_config=CHAT_CONFIG, pages=[page])
    m = re.search(r'id="chat-config">(\{.*?\})</script>', html, re.S)
    assert m, "chat-config island not found"
    cfg = json.loads(m.group(1))
    assert cfg["endpoint"] == "https://ask.moui.co/api"
    assert cfg["gate"] == {"scheme": "access-code", "check": "https://ask.moui.co/api/check"}
    assert "code" not in cfg            # no secret in the page


# ---------------------------------------------------------------------------
# Test 3: non-chat pages are NOT injected
# ---------------------------------------------------------------------------

def test_compose_page_no_chat_feature_no_island(tmp_path):
    """A page with no chat feature body item must not carry the chat-config island."""
    page_no_chat = {
        "title": "About",
        "route": "/about",
        "folder": tmp_path,
        "layout": "minimal",   # suppress chrome so we don't need icons_dir in ctx
        "width": "content",
        "body": [],
        "og": {},
    }
    grove_no_chat = {**GROVE, "features": []}
    html = compose_page(page_no_chat, grove_no_chat, CTX, grove_root=tmp_path, posts=[],
                        feature_endpoints={}, chat_config=CHAT_CONFIG, pages=[page_no_chat])
    assert 'id="chat-config"' not in html


# ---------------------------------------------------------------------------
# Test 4: island is absent when chat_config=None (default)
# ---------------------------------------------------------------------------

def test_compose_page_no_chat_config_no_island(tmp_path):
    """When chat_config is None, no island is injected even for chat pages."""
    # This path is only valid if the grove has NO chat features (otherwise
    # build() raises BuildError). Here we call compose_page directly bypassing
    # the guard to confirm the injection logic itself is gated on chat_config.
    page = _page(tmp_path)
    html = compose_page(page, GROVE, CTX, grove_root=tmp_path, posts=[],
                        feature_endpoints=FEATURE_ENDPOINTS,
                        chat_config=None, pages=[page])
    assert 'id="chat-config"' not in html


# ---------------------------------------------------------------------------
# Test 5: compose_page raises when chat_config set but pages=None
# ---------------------------------------------------------------------------

def test_compose_page_raises_when_chat_config_set_and_pages_none(tmp_path):
    """compose_page must raise ValueError when chat_config is provided but pages is None."""
    page = _page(tmp_path)
    with pytest.raises(ValueError, match="pages="):
        compose_page(page, GROVE, CTX, grove_root=tmp_path, posts=[],
                     feature_endpoints=FEATURE_ENDPOINTS,
                     chat_config=CHAT_CONFIG, pages=None)


# ---------------------------------------------------------------------------
# Test 6: build() raises BuildError for a chat grove without chat_config
# ---------------------------------------------------------------------------

def _make_minimal_chat_grove(tmp_path: Path) -> Path:
    """Minimal grove on disk: grove.yaml with one chat feature + empty posts/."""
    grove_root = tmp_path / "content" / "chat-grove"
    grove_root.mkdir(parents=True)
    (grove_root / "grove.yaml").write_text(yaml.dump({
        "id": "chat-grove",
        "title": "Chat Grove",
        "lang": "en",
        "og": {
            "title": "Chat Grove",
            "description": "Minimal chat grove for testing.",
            "image": "assets/og.png",
            "twitter_card": "summary",
        },
        "features": [
            {"type": "chat", "id": "assistant", "ask": "converse", "persist": "none"}
        ],
    }))
    (grove_root / "posts").mkdir()
    return grove_root


def test_build_raises_when_chat_grove_has_no_chat_config(tmp_path):
    """build() must raise BuildError before going deep when chat features exist
    but chat_config was not supplied."""
    from shapes.grove.exporters.build import build, BuildError

    grove_root = _make_minimal_chat_grove(tmp_path)
    with pytest.raises(BuildError, match="chat feature"):
        build(grove_root, corpus_root=None,
              base_url="https://example.com",
              crawlable="full",
              feature_endpoints={"assistant": "https://ask.moui.co"},
              chat_config=None,
              service_worker=False)
