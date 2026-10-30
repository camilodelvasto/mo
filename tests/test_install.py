"""Tests for mo <shape> install — dependency installation and verification."""
from pathlib import Path

import pytest
import yaml


PROTO = Path(__file__).resolve().parent.parent


def test_get_import_map_returns_mapping():
    """import_map from manifest is returned as a dict."""
    from cli.deps import get_import_map

    manifest = {
        "dependencies": {
            "python": {
                "core": ["pyyaml>=6.0"],
                "import_map": {"pyyaml": "yaml"}
            }
        }
    }
    assert get_import_map(manifest) == {"pyyaml": "yaml"}


def test_get_import_map_empty_when_missing():
    """No import_map block returns empty dict."""
    from cli.deps import get_import_map

    manifest = {"dependencies": {"python": {"core": ["pyyaml>=6.0"]}}}
    assert get_import_map(manifest) == {}


def test_get_import_map_empty_when_no_deps():
    """No dependencies block at all returns empty dict."""
    from cli.deps import get_import_map

    manifest = {}
    assert get_import_map(manifest) == {}


def test_verify_import_succeeds_for_installed_package():
    """verify_import returns True for a package that can be imported."""
    from cli.deps import verify_import

    assert verify_import("yaml", "pyyaml") is True


def test_verify_import_fails_for_missing_package():
    """verify_import returns False for a package that cannot be imported."""
    from cli.deps import verify_import

    assert verify_import("nonexistent_pkg_xyz", "nonexistent-pkg-xyz") is False


def test_verify_import_uses_import_map():
    """verify_import with mapped name imports correctly."""
    from cli.deps import verify_import

    assert verify_import("jsonschema", "jsonschema") is True


def test_install_core_already_satisfied(tmp_path, monkeypatch, capsys):
    """mo <shape> install when core deps are already installed reports success."""
    import json

    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test", "shapes": {
            "grove": {"shape": "grove", "version": "1.0.0", "local": True}
        }
    }))
    shape_dir = tmp_path / "shapes" / "grove"
    shape_dir.mkdir(parents=True)
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "grove", "version": "1.0.0", "type": "renderer",
        "description": "test",
        "capabilities": {"render": [{"type": "grove"}]},
        "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
        "permissions": {"filesystem": {"read": [], "write": []}},
        "dependencies": {"python": {
            "core": ["pyyaml>=6.0", "jsonschema>=4.0"],
            "import_map": {"pyyaml": "yaml"}
        }}
    }))

    monkeypatch.chdir(tmp_path)

    from cli.commands.install import run
    result = run(tmp_path, "grove", [])

    captured = capsys.readouterr()
    assert "already satisfied" in captured.out.lower() or "✓" in captured.out
    assert result == 0


def test_install_no_deps_declared(tmp_path, monkeypatch, capsys):
    """mo <shape> install when shape has no dependencies reports no-op."""
    import json

    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test", "shapes": {
            "leaf": {"shape": "leaf", "version": "1.0.0", "local": True}
        }
    }))
    shape_dir = tmp_path / "shapes" / "leaf"
    shape_dir.mkdir(parents=True)
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "leaf", "version": "1.0.0", "type": "renderer",
        "description": "test",
        "capabilities": {"render": [{"type": "post"}]},
        "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
        "permissions": {"filesystem": {"read": [], "write": []}}
    }))

    monkeypatch.chdir(tmp_path)

    from cli.commands.install import run
    result = run(tmp_path, "leaf", [])

    captured = capsys.readouterr()
    assert "no dependencies" in captured.out.lower()
    assert result == 0


def test_cli_routes_install_command(tmp_path, monkeypatch, capsys):
    """mo grove install routes through the CLI entry point."""
    import json

    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test", "shapes": {
            "grove": {"shape": "grove", "version": "1.0.0", "local": True}
        }
    }))
    shape_dir = tmp_path / "shapes" / "grove"
    shape_dir.mkdir(parents=True)
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "grove", "version": "1.0.0", "type": "renderer",
        "description": "test",
        "capabilities": {"render": [{"type": "grove"}]},
        "schemas": {"extends": [], "defines": [], "deposits_to": "content/schema/"},
        "permissions": {"filesystem": {"read": [], "write": []}},
        "dependencies": {"python": {
            "core": ["pyyaml>=6.0"],
            "import_map": {"pyyaml": "yaml"}
        }}
    }))

    monkeypatch.chdir(tmp_path)

    from cli.moui import main
    main(["grove", "install"])
