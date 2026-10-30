"""Tests for mo grove init CLI command."""
import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

# Path to the real init_post.py for use in test fixtures
_REAL_INIT_POST = Path(__file__).resolve().parent.parent / "shapes" / "grove" / "exporters" / "init_post.py"


def _make_grove_corpus(tmp_path):
    """Create minimal corpus with grove shape and content directory."""
    (tmp_path / "moui.json").write_text(json.dumps({
        "v": 1, "name": "test", "shapes": {
            "grove": {"shape": "grove", "version": "0.1.0", "local": True}
        }
    }))
    shape_dir = tmp_path / "shapes" / "grove"
    shape_dir.mkdir(parents=True)
    (shape_dir / "shape.manifest.yaml").write_text(yaml.dump({
        "name": "grove", "type": "renderer",
        "capabilities": {
            "init": [{"adapter": "exporters/init_post.py"}]
        }
    }))

    # Exporters: layouts module + real init_post module
    exporters_dir = shape_dir / "exporters"
    exporters_dir.mkdir()
    (exporters_dir / "layouts.py").write_text(
        'LAYOUTS = {"article": None, "quote": None}\n'
    )
    shutil.copy(_REAL_INIT_POST, exporters_dir / "init_post.py")

    # Grove content
    grove_root = tmp_path / "content" / "website" / "en"
    posts_dir = grove_root / "posts"
    posts_dir.mkdir(parents=True)
    (grove_root / "grove.yaml").write_text(yaml.dump({
        "id": "test-grove", "title": "Test", "lang": "en"
    }))
    return grove_root, posts_dir


def test_init_single_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    grove_root, posts_dir = _make_grove_corpus(tmp_path)

    md = posts_dir / "my-new-post.md"
    md.write_text("Hello world.\n")

    from cli.moui import main
    main(["grove", "init", str(md)])

    text = md.read_text()
    assert text.startswith("---\n")
    assert 'title: "My New Post"' in text
    assert "Hello world." in text


def test_init_directory_batch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    grove_root, posts_dir = _make_grove_corpus(tmp_path)

    (posts_dir / "one.md").write_text("Body one.\n")
    (posts_dir / "two.md").write_text("Body two.\n")
    (posts_dir / "already.md").write_text("---\ntitle: Exists\n---\nbody\n")

    from cli.moui import main
    main(["grove", "init", str(grove_root)])

    assert (posts_dir / "one.md").read_text().startswith("---\n")
    assert (posts_dir / "two.md").read_text().startswith("---\n")
    # already.md should be untouched
    assert 'title: "Already"' not in (posts_dir / "already.md").read_text()
    assert "title: Exists" in (posts_dir / "already.md").read_text()


def test_init_creates_file_if_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    grove_root, posts_dir = _make_grove_corpus(tmp_path)

    target = posts_dir / "brand-new.md"
    assert not target.exists()

    from cli.moui import main
    main(["grove", "init", str(target)])

    assert target.exists()
    text = target.read_text()
    assert text.startswith("---\n")
    assert 'title: "Brand New"' in text


def test_init_discovers_sections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    grove_root, posts_dir = _make_grove_corpus(tmp_path)
    (posts_dir / "architecture").mkdir()
    (posts_dir / "tutorials").mkdir()

    md = posts_dir / "test.md"
    md.write_text("body\n")

    from cli.moui import main
    main(["grove", "init", str(md)])

    text = md.read_text()
    assert "architecture" in text
    assert "tutorials" in text
