"""Test the CLI loader — reads moui.json and resolves shape instance paths."""
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def test_load_corpus_reads_moui_json():
    from cli.loader import load_corpus

    corpus = load_corpus(ROOT)
    assert corpus["v"] == 1
    assert isinstance(corpus["name"], str) and corpus["name"]
    assert isinstance(corpus["shapes"], dict) and corpus["shapes"]


def test_load_corpus_throws_on_missing_moui_json(tmp_path):
    from cli.loader import load_corpus

    with pytest.raises(FileNotFoundError):
        load_corpus(tmp_path)


def test_resolve_shape_returns_path_and_manifest():
    from cli.loader import load_corpus, resolve_shape

    corpus = load_corpus(ROOT)
    instance_name = next(iter(corpus["shapes"]))
    shape_entry = corpus["shapes"][instance_name]

    shape = resolve_shape(corpus, instance_name, ROOT)
    assert shape["instance_name"] == instance_name
    assert shape["shape_name"] == shape_entry["shape"]
    assert shape["version"] == shape_entry["version"]
    assert shape["path"].is_dir()
    assert isinstance(shape["manifest"]["name"], str)


def test_resolve_shape_throws_on_unknown_instance():
    from cli.loader import load_corpus, resolve_shape

    corpus = load_corpus(ROOT)
    with pytest.raises(KeyError):
        resolve_shape(corpus, "nonexistent", ROOT)


def test_resolve_all_shapes():
    from cli.loader import load_corpus, resolve_all_shapes

    corpus = load_corpus(ROOT)
    shapes = resolve_all_shapes(corpus, ROOT)
    assert set(shapes.keys()) == set(corpus["shapes"].keys())
    for name, shape in shapes.items():
        assert shape["path"].is_dir()
        assert isinstance(shape["manifest"]["name"], str)
