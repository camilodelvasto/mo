import csv
import json
import sqlite3

import pytest
import yaml

from shapes.sheets.src.fields import Field, parse_fields
from shapes.sheets.src.locale import resolve_locale
from shapes.sheets.src.rebuild import rebuild_state


@pytest.fixture
def populated_sheet(sheet_dir):
    """Sheet with two rows in state.sqlite."""
    ops = [
        {
            "op": "insert",
            "ts": "2026-05-01T10:00:00Z",
            "id": "r001",
            "values": {
                "name": "Alice",
                "amount": 1234.56,
                "status": "new",
                "notes": "First entry",
            },
        },
        {
            "op": "insert",
            "ts": "2026-05-02T11:00:00Z",
            "id": "r002",
            "values": {
                "name": "Bob",
                "amount": 7890.12,
                "status": "done",
                "notes": "Second entry",
            },
        },
    ]
    ops_path = sheet_dir / "ops.jsonl"
    ops_path.write_text("\n".join(json.dumps(o) for o in ops) + "\n")
    rebuild_state(sheet_dir)
    return sheet_dir


def _read_csv(path, delimiter=","):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f, delimiter=delimiter))


def test_csv_export_all_fields(populated_sheet, tmp_path):
    from shapes.sheets.renderer.csv.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    fields = parse_fields(sheet)
    locale = resolve_locale("en_US")

    paths = export(populated_sheet, fields, {}, tmp_path, locale)

    assert len(paths) == 1
    rows = _read_csv(paths[0])
    assert rows[0] == [f.label for f in fields]  # header row uses labels
    assert len(rows) == 3  # header + 2 data rows


def test_csv_export_filtered_fields(populated_sheet, tmp_path):
    from shapes.sheets.renderer.csv.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    all_fields = parse_fields(sheet)
    selected = [f for f in all_fields if f.name in ("name", "amount")]

    locale = resolve_locale("en_US")
    paths = export(populated_sheet, selected, {}, tmp_path, locale)

    rows = _read_csv(paths[0])
    assert rows[0] == ["Name", "Amount (EUR)"]
    assert rows[1][0] == "Alice"


def test_csv_export_german_locale(populated_sheet, tmp_path):
    from shapes.sheets.renderer.csv.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    all_fields = parse_fields(sheet)
    selected = [f for f in all_fields if f.name in ("name", "amount")]

    locale = resolve_locale("de_DE")
    paths = export(populated_sheet, selected, {}, tmp_path, locale)

    rows = _read_csv(paths[0], delimiter=";")
    assert rows[0] == ["Name", "Amount (EUR)"]
    # German decimal: 1234.56 -> "1.234,56"
    assert rows[1][1] == "1.234,56"
    assert rows[2][1] == "7.890,12"


def test_csv_export_empty_sheet(sheet_dir, tmp_path):
    """Empty state.sqlite produces headers-only file."""
    from shapes.sheets.renderer.csv.export import export

    rebuild_state(sheet_dir)
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    fields = parse_fields(sheet)
    locale = resolve_locale("en_US")

    paths = export(sheet_dir, fields, {}, tmp_path, locale)

    rows = _read_csv(paths[0])
    assert len(rows) == 1  # header only
    assert rows[0] == [f.label for f in fields]


def test_csv_export_encoding_bom(populated_sheet, tmp_path):
    from shapes.sheets.renderer.csv.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    fields = parse_fields(sheet)
    locale = resolve_locale("en_US")

    paths = export(populated_sheet, fields, {}, tmp_path, locale)

    raw = paths[0].read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM
