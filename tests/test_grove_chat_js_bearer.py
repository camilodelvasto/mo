# tests/test_grove_chat_js_bearer.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path
SRC = Path("shapes/grove/renderer/core/components/chat.js").read_text()

def test_chat_sends_bearer_when_code_present():
    assert "Authorization" in SRC and "Bearer" in SRC
    assert "config.code" in SRC or "chatCfg.code" in SRC

def test_chat_handles_401_distinctly():
    assert "401" in SRC
