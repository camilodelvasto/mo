"""Tests for sheets CLI utility functions."""
import json
import yaml
import pytest


@pytest.fixture
def sheets_corpus(tmp_path):
    """Minimal corpus with a sheets shape and one sheet in content."""
    sheet_data = {
        "title": "Test Sheet",
        "port": 4500,
        "fields": {"id": "primary", "name": "string"},
        "pipeline": {"inputs": {}},
    }
    content = tmp_path / "content" / "mysheet"
    content.mkdir(parents=True)
    (content / "sheet.yaml").write_text(yaml.dump(sheet_data, sort_keys=False))
    (content / "ops.jsonl").write_text("")

    manifest = {
        "v": 1,
        "name": "test",
        "shapes": {"sheets": {"shape": "sheets", "version": "0.1.0", "local": True}},
    }
    (tmp_path / "moui.json").write_text(json.dumps(manifest))
    return tmp_path


def test_resolve_sheet_by_path(sheets_corpus):
    from shapes.sheets.src.cli_utils import resolve_sheet

    result = resolve_sheet("content/mysheet", sheets_corpus)
    assert result == (sheets_corpus / "content" / "mysheet").resolve()
    assert (result / "sheet.yaml").exists()


def test_resolve_sheet_by_content_shorthand(sheets_corpus):
    from shapes.sheets.src.cli_utils import resolve_sheet

    result = resolve_sheet("mysheet", sheets_corpus)
    assert result == (sheets_corpus / "content" / "mysheet").resolve()


def test_resolve_sheet_not_found(sheets_corpus):
    from shapes.sheets.src.cli_utils import resolve_sheet

    with pytest.raises(SystemExit):
        resolve_sheet("nonexistent", sheets_corpus)


def test_read_sheet_port(sheets_corpus):
    from shapes.sheets.src.cli_utils import read_sheet_port

    sheet_dir = sheets_corpus / "content" / "mysheet"
    assert read_sheet_port(sheet_dir) == 4500


def test_read_sheet_port_not_declared(sheets_corpus):
    from shapes.sheets.src.cli_utils import read_sheet_port

    sheet_dir = sheets_corpus / "content" / "mysheet"
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    del sheet["port"]
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))
    assert read_sheet_port(sheet_dir) is None


def test_bind_port_finds_free_port():
    from shapes.sheets.src.cli_utils import bind_port

    port = bind_port(None)
    assert 4300 <= port < 4310


def test_discover_sheets(sheets_corpus):
    from shapes.sheets.src.cli_utils import discover_sheets

    sheets = discover_sheets(sheets_corpus)
    assert len(sheets) == 1
    assert sheets[0]["name"] == "mysheet"
    assert sheets[0]["port"] == 4500
