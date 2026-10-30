"""Tests for sheets CLI — exercises command adapters and utilities."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from shapes.sheets.src.cli_utils import resolve_sheet, read_sheet_port, discover_sheets


def test_resolve_sheet_by_path(corpus_root):
    sheet_dir = resolve_sheet("content/test", corpus_root)
    assert sheet_dir == (corpus_root / "content" / "test").resolve()
    assert (sheet_dir / "sheet.yaml").exists()


def test_resolve_sheet_by_content_shorthand(corpus_root):
    sheet_dir = resolve_sheet("test", corpus_root)
    assert sheet_dir == (corpus_root / "content" / "test").resolve()


def test_resolve_sheet_not_found(corpus_root):
    with pytest.raises(SystemExit):
        resolve_sheet("nonexistent", corpus_root)


def test_read_sheet_port_declared(corpus_root):
    sheet_dir = corpus_root / "content" / "test"
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet["port"] = 4500
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))
    assert read_sheet_port(sheet_dir) == 4500


def test_read_sheet_port_not_declared(corpus_root):
    sheet_dir = corpus_root / "content" / "test"
    assert read_sheet_port(sheet_dir) is None


def test_status_discovers_sheets(corpus_root):
    sheet_dir = corpus_root / "content" / "test"
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet["port"] = 4500
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))

    sheets = discover_sheets(corpus_root)
    assert len(sheets) >= 1
    assert any(s["name"] == "test" for s in sheets)
    assert any(s["port"] == 4500 for s in sheets)


def _load_adapter(name: str):
    """Load a sheets command adapter by name."""
    import importlib.util
    adapter_path = Path(__file__).resolve().parent.parent / "shapes" / "sheets" / "commands" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"sheets_{name}", adapter_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ingest_writes_file(corpus_root, monkeypatch):
    monkeypatch.chdir(corpus_root)
    sys.path.insert(0, str(corpus_root))

    adapter = _load_adapter("ingest")
    adapter.run(corpus_root, "sheets", ["content/test", "NEW\nApt at Vossstrasse 35"])

    inbox = corpus_root / "content" / "test" / "ingest" / "inbox"
    files = list(inbox.iterdir())
    assert len(files) == 1
    assert files[0].read_text().startswith("NEW\n")


def test_rebuild_command(corpus_root, monkeypatch):
    monkeypatch.chdir(corpus_root)
    sys.path.insert(0, str(corpus_root))

    with patch("shapes.sheets.src.rebuild.rebuild_state") as mock_rebuild:
        adapter = _load_adapter("rebuild")
        adapter.run(corpus_root, "sheets", ["content/test"])

    mock_rebuild.assert_called_once()


def _add_exports_yaml(corpus_root, exports_dict):
    sheet_dir = corpus_root / "content" / "test"
    (sheet_dir / "exports.yaml").write_text(
        yaml.dump({"exports": exports_dict}, sort_keys=False)
    )


def _populate_sheet(corpus_root):
    from shapes.sheets.src.rebuild import rebuild_state
    sheet_dir = corpus_root / "content" / "test"
    ops = [
        {
            "op": "insert", "ts": "2026-05-01T10:00:00Z", "id": "r001",
            "values": {"name": "Alice", "amount": 1234.56, "status": "new", "notes": ""},
        },
    ]
    (sheet_dir / "ops.jsonl").write_text(
        "\n".join(json.dumps(o) for o in ops) + "\n"
    )
    rebuild_state(sheet_dir)


def test_export_list_shows_configs(corpus_root, monkeypatch, capsys):
    monkeypatch.chdir(corpus_root)
    sys.path.insert(0, str(corpus_root))
    _add_exports_yaml(corpus_root, {"local": {"formats": ["csv", "xlsx"]}})

    adapter = _load_adapter("export_cmd")
    adapter.run(corpus_root, "sheets", ["content/test"])

    out = capsys.readouterr().out
    assert "local" in out
    assert "csv" in out


def test_export_runs_csv(corpus_root, monkeypatch):
    monkeypatch.chdir(corpus_root)
    sys.path.insert(0, str(corpus_root))
    _add_exports_yaml(corpus_root, {"local": {"formats": ["csv"]}})
    _populate_sheet(corpus_root)

    adapter = _load_adapter("export_cmd")
    adapter.run(corpus_root, "sheets", ["content/test", "local"])

    export_dir = corpus_root / "content" / "test" / "exports" / "local"
    assert (export_dir / "test.csv").exists()


def test_export_dry_run(corpus_root, monkeypatch, capsys):
    monkeypatch.chdir(corpus_root)
    sys.path.insert(0, str(corpus_root))
    _add_exports_yaml(corpus_root, {"local": {"formats": ["csv"]}})
    _populate_sheet(corpus_root)

    adapter = _load_adapter("export_cmd")
    adapter.run(corpus_root, "sheets", ["content/test", "local", "-n"])

    out = capsys.readouterr().out
    assert "dry-run" in out
