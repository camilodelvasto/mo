"""Test the mo CLI entry point — path resolution and command routing."""
import json
from pathlib import Path

import pytest
import yaml


def test_resolve_content_path_exact_match(tmp_path):
    """When the exact path exists, return it."""
    from cli.moui import resolve_content_path

    f = tmp_path / "deck.yaml"
    f.write_text("instance: deck")
    assert resolve_content_path(tmp_path / "deck.yaml") == f


def test_resolve_content_path_infers_yaml(tmp_path):
    """When path has no extension, try .yaml first."""
    from cli.moui import resolve_content_path

    f = tmp_path / "deck.yaml"
    f.write_text("instance: deck")
    assert resolve_content_path(tmp_path / "deck") == f


def test_resolve_content_path_infers_yml(tmp_path):
    """When path has no extension and .yaml doesn't exist, try .yml."""
    from cli.moui import resolve_content_path

    f = tmp_path / "deck.yml"
    f.write_text("instance: deck")
    assert resolve_content_path(tmp_path / "deck") == f


def test_resolve_content_path_prefers_yaml_over_yml(tmp_path):
    """When both .yaml and .yml exist, .yaml wins."""
    from cli.moui import resolve_content_path

    (tmp_path / "deck.yaml").write_text("instance: deck")
    (tmp_path / "deck.yml").write_text("instance: deck")
    assert resolve_content_path(tmp_path / "deck") == tmp_path / "deck.yaml"


def test_resolve_content_path_raises_on_missing(tmp_path):
    """When no file matches, raise FileNotFoundError."""
    from cli.moui import resolve_content_path

    with pytest.raises(FileNotFoundError):
        resolve_content_path(tmp_path / "nope")


def test_main_serve_resolves_shape_and_calls_server(tmp_path, monkeypatch):
    """mo deck serve <path> resolves shape instance and calls server."""
    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1,
        "name": "test-corpus",
        "shapes": {
            "deck": {"shape": "deck", "version": "1.0.0", "local": True}
        }
    }))

    shape_dir = tmp_path / "shapes" / "deck"
    shape_dir.mkdir(parents=True)
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "deck", "type": "renderer"
    }))
    server_dir = shape_dir / "renderer" / "shell-web"
    server_dir.mkdir(parents=True)
    (server_dir / "server.py").write_text(
        "def serve(content_path, shape_path, corpus_root): pass"
    )

    content_dir = tmp_path / "content"
    content_dir.mkdir()
    content_file = content_dir / "my-deck.yaml"
    content_file.write_text(yaml.dump({
        "instance": "deck",
        "theme": "default"
    }))

    monkeypatch.chdir(tmp_path)

    from cli.moui import main
    main(["deck", "serve", "content/my-deck"])
