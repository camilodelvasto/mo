# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import json
import re
from shapes.grove.exporters.chat_config import chat_presentation, emit_chat_config

GROVE = {"features": [{"type": "chat", "id": "assistant", "ask": "converse",
                       "persist": "local", "name": "Persona Flexible", "intro": "Hola"}]}
PAGES = [{"route": "/chatbot", "body": [{"feature": "assistant"}]}]
CTX = {"base_path": ""}


def test_presentation_keyed_by_route_with_fields():
    chats = chat_presentation(GROVE, PAGES, CTX)
    assert "/chatbot/" in chats
    entry = chats["/chatbot/"]
    assert entry["ask"] == "converse" and entry["persist"] == "local"
    assert entry["name"] == "Persona Flexible"
    assert "intro_html" in entry and "route" not in entry     # route is the key, not a field


def test_emit_blob_carries_endpoint_code_chats():
    block = emit_chat_config(GROVE, PAGES, CTX, endpoint="https://ask.moui.co/api", code="C0DE")
    m = re.search(r'id="chat-config">(\{.*?\})</script>', block, re.S)
    cfg = json.loads(m.group(1))
    assert cfg["endpoint"] == "https://ask.moui.co/api"
    assert cfg["code"] == "C0DE"
    assert cfg["chats"]["/chatbot/"]["ask"] == "converse"
    assert "markdown-it" in block                              # the md script rides along


def test_emit_omits_code_when_absent():
    block = emit_chat_config(GROVE, PAGES, CTX, endpoint="https://ask.moui.co/api", code=None)
    m = re.search(r'id="chat-config">(\{.*?\})</script>', block, re.S)
    assert "code" not in json.loads(m.group(1))


def test_dev_and_static_use_same_emitter(monkeypatch):
    # the dev server's chat-config block must be the shared emitter's output
    import sys
    from pathlib import Path
    shell_web = Path(__file__).resolve().parent.parent / 'shapes' / 'grove' / 'renderer' / 'shell-web'
    exporters = Path(__file__).resolve().parent.parent / 'shapes' / 'grove' / 'exporters'
    monkeypatch.syspath_prepend(str(shell_web))
    monkeypatch.syspath_prepend(str(exporters))
    # force a fresh import of server so monkeypatched sys.path applies
    if 'server' in sys.modules:
        monkeypatch.delitem(sys.modules, 'server')
    import importlib
    srv = importlib.import_module('server')
    from shapes.grove.exporters import chat_config
    grove = {"features": [{"type": "chat", "id": "a", "ask": "converse"}]}
    pages = [{"route": "/c", "body": [{"feature": "a"}]}]
    ctx = {"base_path": ""}
    expected = chat_config.emit_chat_config(grove, pages, ctx, endpoint="http://e", code=None)
    # server._chat_presentation is gone; server imports chat_presentation from the shared module
    assert srv.chat_presentation is chat_config.chat_presentation


def test_avatar_normalization():
    base = "/sub"
    ctx = {"base_path": base}
    grove_abs = {"features": [{"type": "chat", "id": "bot", "ask": "converse",
                                "avatar": "https://cdn.example.com/bot.png"}]}
    grove_rooted = {"features": [{"type": "chat", "id": "bot", "ask": "converse",
                                   "avatar": "/images/bot.png"}]}
    grove_bare = {"features": [{"type": "chat", "id": "bot", "ask": "converse",
                                 "avatar": "bot.png"}]}
    pages = [{"route": "/chatbot", "body": [{"feature": "bot"}]}]

    # absolute URL passes through unchanged
    chats = chat_presentation(grove_abs, pages, ctx)
    assert chats["/chatbot/"]["avatar"] == "https://cdn.example.com/bot.png"

    # /rooted path gets base_path prepended
    chats = chat_presentation(grove_rooted, pages, ctx)
    assert chats["/chatbot/"]["avatar"] == "/sub/images/bot.png"

    # bare name gets base_path + "/" prepended
    chats = chat_presentation(grove_bare, pages, ctx)
    assert chats["/chatbot/"]["avatar"] == "/sub/bot.png"


def test_instructions_rendered_with_collapsible_flag():
    grove = {"features": [{"type": "chat", "id": "c", "ask": "a",
             "intro": "Hola.",
             "instructions": {"collapsible": False, "summary": "¿Cómo?",
                              "body": "Texto de ayuda."}}]}
    pages = [{"route": "/chat/", "body": [{"feature": "c"}]}]
    chats = chat_presentation(grove, pages, {"base_path": ""})
    e = chats["/chat/"]
    assert "Texto de ayuda" in e["instructions_html"]
    assert e["instructions_collapsible"] is False
    assert e["instructions_summary"] == "¿Cómo?"


def test_no_instructions_key_when_absent():
    grove = {"features": [{"type": "chat", "id": "c", "ask": "a", "intro": "Hola."}]}
    pages = [{"route": "/chat/", "body": [{"feature": "c"}]}]
    e = chat_presentation(grove, pages, {"base_path": ""})["/chat/"]
    assert "instructions_html" not in e
