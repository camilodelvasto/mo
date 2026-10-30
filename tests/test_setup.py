"""Tests for mo setup — corpus onboarding orchestrator."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


PROTO = Path(__file__).resolve().parent.parent


def test_detect_env_venv(monkeypatch):
    """When sys.prefix != sys.base_prefix, detect as venv."""
    from cli.commands.setup import detect_environment

    monkeypatch.setattr(sys, "prefix", "/home/user/project/.venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr")

    env = detect_environment()
    assert env["type"] == "venv"
    assert env["path"] == "/home/user/project/.venv"


def test_detect_env_pipx(monkeypatch):
    """When sys.executable is inside a pipx path, detect as pipx."""
    from cli.commands.setup import detect_environment

    monkeypatch.setattr(sys, "prefix", "/home/user/.local/pipx/venvs/moui")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    monkeypatch.setattr(sys, "executable", "/home/user/.local/pipx/venvs/moui/bin/python")

    env = detect_environment()
    assert env["type"] == "pipx"


def test_detect_env_system(monkeypatch):
    """When prefix == base_prefix and no pipx, detect as system."""
    from cli.commands.setup import detect_environment

    monkeypatch.setattr(sys, "prefix", "/usr")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")

    env = detect_environment()
    assert env["type"] == "system"
    assert env["path"] == "/usr"


def _make_corpus(tmp_path, shapes_config):
    """Helper: create a minimal corpus with given shapes."""
    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test", "shapes": {
            k: {kk: vv for kk, vv in v.items() if kk != "_manifest"}
            for k, v in shapes_config.items()
        }
    }))
    for name, cfg in shapes_config.items():
        shape_dir = tmp_path / "shapes" / name
        shape_dir.mkdir(parents=True)
        manifest = cfg.get("_manifest", {
            "name": name, "version": "1.0.0", "type": "renderer",
            "description": "test",
            "capabilities": {"render": [{"type": "test"}]},
            "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
            "permissions": {"filesystem": {"read": [], "write": []}},
        })
        (shape_dir / "shape.manifest.yaml").write_text(yaml.dump(manifest))


def test_setup_all_shapes_satisfied(tmp_path, monkeypatch, capsys):
    """mo setup with all deps already installed exits 0."""
    _make_corpus(tmp_path, {
        "grove": {
            "shape": "grove", "version": "1.0.0", "local": True,
            "_manifest": {
                "name": "grove", "version": "1.0.0", "type": "renderer",
                "description": "test",
                "capabilities": {"render": [{"type": "grove"}]},
                "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
                "permissions": {"filesystem": {"read": [], "write": []}},
                "dependencies": {"python": {
                    "core": ["pyyaml>=6.0"],
                    "import_map": {"pyyaml": "yaml"}
                }}
            }
        },
        "leaf": {"shape": "leaf", "version": "1.0.0", "local": True}
    })

    monkeypatch.chdir(tmp_path)

    from cli.commands.setup import run
    exit_code = run(tmp_path, ["--non-interactive"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "grove" in captured.out
    assert "leaf" in captured.out


def test_setup_partial_failure(tmp_path, monkeypatch, capsys):
    """One shape fails, others succeed: exit 1, passing shapes show checkmark."""
    _make_corpus(tmp_path, {
        "good": {
            "shape": "good", "version": "1.0.0", "local": True,
            "_manifest": {
                "name": "good", "version": "1.0.0", "type": "renderer",
                "description": "test",
                "capabilities": {"render": [{"type": "test"}]},
                "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
                "permissions": {"filesystem": {"read": [], "write": []}},
                "dependencies": {"python": {
                    "core": ["pyyaml>=6.0"],
                    "import_map": {"pyyaml": "yaml"}
                }}
            }
        },
        "broken": {
            "shape": "broken", "version": "1.0.0", "local": True,
            "_manifest": {
                "name": "broken", "version": "1.0.0", "type": "renderer",
                "description": "test",
                "capabilities": {"render": [{"type": "test"}]},
                "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
                "permissions": {"filesystem": {"read": [], "write": []}},
                "dependencies": {"python": {
                    "core": ["nonexistent-pkg-that-will-fail>=99.0"]
                }}
            }
        }
    })

    monkeypatch.chdir(tmp_path)

    from cli.commands.setup import run
    exit_code = run(tmp_path, ["--non-interactive"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "✓" in captured.out  # good shape passed
    assert "✗" in captured.out  # broken shape failed


def test_setup_non_interactive_skips_remotes(tmp_path, monkeypatch, capsys):
    """--non-interactive skips remote setup and notes it in output."""
    _make_corpus(tmp_path, {
        "leaf": {"shape": "leaf", "version": "1.0.0", "local": True}
    })

    monkeypatch.chdir(tmp_path)

    from cli.commands.setup import run
    run(tmp_path, ["--non-interactive"])

    captured = capsys.readouterr()
    assert "non-interactive" in captured.out.lower() or "skipped" in captured.out.lower()


def test_cli_routes_setup_command(tmp_path, monkeypatch, capsys):
    """mo setup routes through the CLI entry point."""
    _make_corpus(tmp_path, {
        "leaf": {"shape": "leaf", "version": "1.0.0", "local": True}
    })

    monkeypatch.chdir(tmp_path)

    from cli.moui import main
    with pytest.raises(SystemExit) as exc_info:
        main(["setup", "--non-interactive"])
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "Environment" in captured.out or "Python" in captured.out
