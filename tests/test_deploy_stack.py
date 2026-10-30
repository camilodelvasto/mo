# tests/test_deploy_stack.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from pathlib import Path
from cli.deploy import stack
from cli.deploy.converge import ConvergeError


def _env():
    return {"remote": "hetzner/x", "domain": "ask.moui.co", "corpus": "cx",
            "content": "content/clients/acme/notes",
            "grove_origins": ["https://ask.moui.co"], "exposed_asks": ["answer"],
            "capabilities": "infrastructure/corpus-server/acme/capabilities.yaml",
            "aws_profile": "bedrock-claude-eu",
            "auth": {"scheme": "access-code", "access_list": "secrets/corpus-server/acme/access.csv"},
            "roles": {"standard": {"cap": 500}}, "default_role": "standard",
            "window": "month",
            "rate_limit": {"per_minute": 60, "block_after": 10, "block_for": "15m"}}

_CAPS_YAML = "capabilities:\n  api.claude:\n    run: [/app/bin/claude-bedrock, --model, m, --region, eu-central-1]\n"


def _common(monkeypatch, adapter):
    monkeypatch.setattr(stack, "resolve_credentials", lambda *a: {})
    monkeypatch.setattr(stack, "_load_ask_yaml",
        lambda root, env: {"asks": [{"id": "answer", "synthesize": {"uses": "api.claude"}}]})
    monkeypatch.setattr(stack, "_read", lambda root, rel: _CAPS_YAML if "capabilities" in rel else "id,code\n")
    monkeypatch.setattr(stack, "shims_present", lambda caps, root: None)
    monkeypatch.setattr(stack, "smoke_models", lambda profile, caps: None)
    monkeypatch.setattr(stack, "resolve_aws_creds", lambda profile: "[default]\n")
    monkeypatch.setattr(stack.converge, "resolve", lambda name: adapter)


def test_rail_runs_gates_then_dispatches_with_secrets(monkeypatch):
    seen = {}
    class Adapter:
        def converge(self, corpus_root, remote, layout, **kw):
            seen.update(access=kw["access_csv"], aws=kw["aws_creds"], caps=kw["capabilities_yaml"])
    _common(monkeypatch, Adapter())
    stack.run(Path("/root"), {"stack": "corpus-server", "converge": "compose"},
              _env(), {"host": "h", "user": "u", "path": "/opt/cs"}, "prod")
    assert seen["aws"] == "[default]\n" and seen["access"] == "id,code\n"
    assert "api.claude" in seen["caps"]


def test_smoke_failure_aborts_before_dispatch(monkeypatch):
    from cli.deploy.smoke import SmokeError
    dispatched = []
    class Adapter:
        def converge(self, *a, **k): dispatched.append(1)
    _common(monkeypatch, Adapter())
    monkeypatch.setattr(stack, "smoke_models",
        lambda profile, caps: (_ for _ in ()).throw(SmokeError("opus not granted")))
    with pytest.raises(SystemExit):
        stack.run(Path("/root"), {"stack": "corpus-server", "converge": "compose"},
                  _env(), {"host": "h", "user": "u", "path": "/opt/cs"}, "prod")
    assert dispatched == []                              # gate failed → no box touch


def test_binding_mismatch_aborts_before_dispatch(monkeypatch):
    dispatched = []
    class Adapter:
        def converge(self, *a, **k): dispatched.append(1)
    _common(monkeypatch, Adapter())
    # ask needs api.claude-json but the committed capabilities binds only api.claude
    monkeypatch.setattr(stack, "_load_ask_yaml",
        lambda root, env: {"asks": [{"id": "answer", "synthesize": {"uses": "api.claude-json"}}]})
    with pytest.raises(SystemExit):
        stack.run(Path("/root"), {"stack": "corpus-server", "converge": "compose"},
                  _env(), {"host": "h", "user": "u", "path": "/opt/cs"}, "prod")
    assert dispatched == []


def test_converge_error_exits_nonzero(monkeypatch):
    class Adapter:
        def converge(self, *a, **k): raise ConvergeError("down")
    _common(monkeypatch, Adapter())
    with pytest.raises(SystemExit) as e:
        stack.run(Path("/root"), {"stack": "corpus-server", "converge": "compose"},
                  _env(), {"host": "h", "user": "u", "path": "/opt/cs"}, "prod")
    assert e.value.code == 1


def test_rail_imports_no_box_toolkit():
    # the rail/adapter boundary: stack.py must not import the box ssh toolkit —
    # every docker/ssh/compose call is the resolved adapter's. (Checks the import
    # path, not a bare "box" substring, so cli.infra.box_layout does not false-match.)
    import cli.deploy.stack as s
    src = Path(s.__file__).read_text()
    assert "cli.sync.corpus.box" not in src, \
        "the rail must not import the box ssh toolkit — that is the adapter's"


def test_singular_grove_origin_is_refused_by_name():
    with pytest.raises(SystemExit, match="now 'grove_origins:'"):
        stack._grove_origins({"grove_origin": "https://www.moui.io"})
