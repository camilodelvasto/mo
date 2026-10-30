import pytest
import logging
from pathlib import Path

from cli.sync.discovery import discover_declarations, ResolvedFolder
from cli.sync.errors import InfrastructureNotFoundError


def _write_yaml(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


MINIMAL_DECL = """\
version: 1
target: {target}
remote: codeberg/sync
encryption:
  type: none
"""


def test_discover_empty_syncs_dir(tmp_path):
    """Empty syncs/ directory returns empty list."""
    syncs = tmp_path / "infrastructure" / "syncs"
    syncs.mkdir(parents=True)
    result = discover_declarations(tmp_path / "infrastructure")
    assert result == []


def test_discover_single_declaration(tmp_path):
    """One declaration resolves to one ResolvedFolder."""
    infra = tmp_path / "infrastructure"
    syncs = infra / "syncs"
    content = tmp_path / "content" / "moui"
    content.mkdir(parents=True)

    _write_yaml(
        syncs / "content" / "moui.yaml",
        MINIMAL_DECL.format(target="../../../content/moui"),
    )

    result = discover_declarations(infra)
    assert len(result) == 1
    assert result[0].folder_path == content
    assert result[0].declaration.remote == "codeberg/sync"
    assert result[0].declaration_path == syncs / "content" / "moui.yaml"


def test_discover_multiple_declarations(tmp_path):
    """Multiple declarations all discovered."""
    infra = tmp_path / "infrastructure"
    syncs = infra / "syncs"
    (tmp_path / "content").mkdir()
    (tmp_path / "personal").mkdir()

    _write_yaml(syncs / "content.yaml", MINIMAL_DECL.format(target="../../content"))
    _write_yaml(syncs / "personal.yaml", MINIMAL_DECL.format(target="../../personal"))

    result = discover_declarations(infra)
    assert len(result) == 2
    paths = {r.folder_path for r in result}
    assert tmp_path / "content" in paths
    assert tmp_path / "personal" in paths


def test_discover_self_declaration(tmp_path):
    """infrastructure/ can declare itself via target: .."""
    infra = tmp_path / "infrastructure"
    syncs = infra / "syncs"
    syncs.mkdir(parents=True)

    _write_yaml(syncs / "self.yaml", MINIMAL_DECL.format(target=".."))
    result = discover_declarations(infra)
    assert len(result) == 1
    assert result[0].folder_path == infra


def test_discover_target_missing_logs_warning(tmp_path, caplog):
    """Declaration with missing target folder is skipped with warning."""
    infra = tmp_path / "infrastructure"
    syncs = infra / "syncs"
    _write_yaml(syncs / "ghost.yaml", MINIMAL_DECL.format(target="../../ghost"))

    with caplog.at_level(logging.WARNING):
        result = discover_declarations(infra)
    assert result == []
    assert "ghost" in caplog.text


def test_discover_no_syncs_dir(tmp_path):
    """Missing syncs/ directory returns empty list."""
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    result = discover_declarations(infra)
    assert result == []


def test_discover_infra_not_found(tmp_path):
    """Non-existent infrastructure path raises."""
    with pytest.raises(InfrastructureNotFoundError):
        discover_declarations(tmp_path / "nope")
