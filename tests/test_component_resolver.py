"""Tests for the component resolver — corpus-root-first, then shape-specific."""
from pathlib import Path

import pytest


def test_resolve_component_returns_corpus_root_when_present(tmp_path):
    from cli.component_resolver import resolve_component

    corpus_comp = tmp_path / "components" / "stat-card"
    corpus_comp.mkdir(parents=True)
    (corpus_comp / "component.yaml").write_text("name: stat-card")

    shape_comp = tmp_path / "shapes" / "deck" / "components" / "stat-card"
    shape_comp.mkdir(parents=True)
    (shape_comp / "component.yaml").write_text("name: stat-card")

    result = resolve_component(
        "stat-card", corpus_root=tmp_path,
        shape_path=tmp_path / "shapes" / "deck",
    )
    assert result == corpus_comp


def test_resolve_component_falls_back_to_shape(tmp_path):
    from cli.component_resolver import resolve_component

    shape_comp = tmp_path / "shapes" / "deck" / "components" / "stat-card"
    shape_comp.mkdir(parents=True)
    (shape_comp / "component.yaml").write_text("name: stat-card")

    result = resolve_component(
        "stat-card", corpus_root=tmp_path,
        shape_path=tmp_path / "shapes" / "deck",
    )
    assert result == shape_comp


def test_resolve_component_raises_when_not_found(tmp_path):
    from cli.component_resolver import resolve_component

    with pytest.raises(FileNotFoundError, match="stat-card"):
        resolve_component(
            "stat-card", corpus_root=tmp_path,
            shape_path=tmp_path / "shapes" / "deck",
        )


def test_resolve_component_raises_when_dir_exists_but_no_yaml(tmp_path):
    from cli.component_resolver import resolve_component

    corpus_comp = tmp_path / "components" / "stat-card"
    corpus_comp.mkdir(parents=True)
    # No component.yaml

    with pytest.raises(FileNotFoundError, match="component.yaml"):
        resolve_component(
            "stat-card", corpus_root=tmp_path,
            shape_path=tmp_path / "shapes" / "deck",
        )
