# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path

import cli.infra.services as S
from cli.infra.services import resolve_chat_binding

_GROVE = {"features": [{"type": "chat", "id": "a", "ask": "advisor"}]}


def _binding(box_env, grove_env):
    # Drive resolve_chat_binding by faking load_target/get_environment at the module level.
    # The module calls them as bare names (imported into the module namespace), so assigning
    # them as attributes on the module object intercepts the calls.
    S.load_target = lambda ref, root: {"_box": box_env}
    S.get_environment = lambda tgt, env: tgt["_box"]
    return resolve_chat_binding(_GROVE, grove_env, "dev", Path("."), with_code=False)


def test_local_dev_uses_http_open():
    b = _binding({"domain": "localhost:8080", "local": True, "auth": {"scheme": "none"}},
                 {"services": {"chat": "content/x"}})
    assert b["endpoint"] == "http://localhost:8080/api"
    assert b["gate"] is None


def test_local_dev_http_gated():
    b = _binding({"domain": "localhost:8080", "local": True, "auth": {"scheme": "access-code"}},
                 {"services": {"chat": "content/x"}})
    assert b["endpoint"] == "http://localhost:8080/api"
    assert b["gate"] == {"scheme": "access-code", "check": "http://localhost:8080/api/check"}


def test_remote_still_https():
    b = _binding({"domain": "ask.moui.co", "auth": {"scheme": "none"}},
                 {"services": {"chat": "content/x"}})
    assert b["endpoint"] == "https://ask.moui.co/api"
