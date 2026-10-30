"""Tests for mo deck build and mo deck deploy CLI commands."""
import json
from pathlib import Path

import pytest
import yaml


_STUB_BUILD_PY = """\
import json, sys

def build(content_path, instance_name, corpus_root, *, encrypted=False, mnemonic=None, rotate=False):
    # Write call record so the test can inspect it.
    record = {
        "content_path": str(content_path),
        "instance_name": instance_name,
        "corpus_root": str(corpus_root),
        "encrypted": encrypted,
        "rotate": rotate,
    }
    (corpus_root / ".corpus" / "_build_call.json").parent.mkdir(parents=True, exist_ok=True)
    (corpus_root / ".corpus" / "_build_call.json").write_text(json.dumps(record))
    build_dir = corpus_root / ".corpus" / "shapes" / "deck" / "builds" / "example" / "test"
    build_dir.mkdir(parents=True, exist_ok=True)
    mnemonic_out = "test mnemonic words" if encrypted else None
    return (build_dir, mnemonic_out)
"""


def _make_corpus(tmp_path):
    """Minimal corpus for CLI tests."""
    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test", "shapes": {
            "deck": {"shape": "deck", "version": "0.4.0", "local": True}
        }
    }))
    shape_dir = tmp_path / "shapes" / "deck"
    shape_dir.mkdir(parents=True)
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "deck", "type": "renderer"
    }))
    exporters_dir = shape_dir / "exporters"
    exporters_dir.mkdir(parents=True)
    (exporters_dir / "build.py").write_text(_STUB_BUILD_PY)
    content_dir = tmp_path / "content" / "example"
    content_dir.mkdir(parents=True)
    content_file = content_dir / "test.yaml"
    content_file.write_text(yaml.dump({
        "instance": "deck", "theme": "default", "title": "T",
        "slides": [{"id": "s1", "layout": "cover", "content": {"heading": "H"}}]
    }))
    return content_file


def _read_call_record(tmp_path):
    return json.loads((tmp_path / ".corpus" / "_build_call.json").read_text())


def test_build_command_calls_build_module(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_corpus(tmp_path)

    from cli.moui import main
    main(["deck", "build", "content/example/test.yaml"])

    record = _read_call_record(tmp_path)
    assert record["encrypted"] is False
    assert record["rotate"] is False


def test_build_encrypted_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_corpus(tmp_path)

    from cli.moui import main
    main(["deck", "build", "content/example/test.yaml", "--encrypted"])

    record = _read_call_record(tmp_path)
    assert record["encrypted"] is True


def test_build_rotate_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_corpus(tmp_path)

    from cli.moui import main
    main(["deck", "build", "content/example/test.yaml", "--encrypted", "--rotate"])

    record = _read_call_record(tmp_path)
    assert record["encrypted"] is True
    assert record["rotate"] is True
