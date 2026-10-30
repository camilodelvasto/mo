import json

import pytest
import yaml

from shapes.sheets.src.fields import parse_fields
from shapes.sheets.src.locale import resolve_locale
from shapes.sheets.src.rebuild import rebuild_state

openpyxl = pytest.importorskip("openpyxl")


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


def test_xlsx_export_creates_file(populated_sheet, tmp_path):
    from shapes.sheets.renderer.xlsx.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    fields = parse_fields(sheet)
    locale = resolve_locale("en_US")

    paths = export(populated_sheet, fields, {}, tmp_path, locale)

    assert len(paths) == 1
    assert paths[0].suffix == ".xlsx"
    assert paths[0].exists()


def test_xlsx_export_headers_are_labels(populated_sheet, tmp_path):
    from shapes.sheets.renderer.xlsx.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    fields = parse_fields(sheet)
    locale = resolve_locale("en_US")

    paths = export(populated_sheet, fields, {}, tmp_path, locale)

    wb = openpyxl.load_workbook(paths[0])
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    assert headers == [f.label for f in fields]


def test_xlsx_export_headers_are_bold(populated_sheet, tmp_path):
    from shapes.sheets.renderer.xlsx.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    fields = parse_fields(sheet)
    locale = resolve_locale("en_US")

    paths = export(populated_sheet, fields, {}, tmp_path, locale)

    wb = openpyxl.load_workbook(paths[0])
    ws = wb.active
    for cell in ws[1]:
        assert cell.font.bold


def test_xlsx_export_frozen_header(populated_sheet, tmp_path):
    from shapes.sheets.renderer.xlsx.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    fields = parse_fields(sheet)
    locale = resolve_locale("en_US")

    paths = export(populated_sheet, fields, {}, tmp_path, locale)

    wb = openpyxl.load_workbook(paths[0])
    ws = wb.active
    assert ws.freeze_panes == "A2"




def test_xlsx_export_numbers_are_numeric(populated_sheet, tmp_path):
    from shapes.sheets.renderer.xlsx.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    all_fields = parse_fields(sheet)
    selected = [f for f in all_fields if f.name in ("name", "amount")]
    locale = resolve_locale("en_US")

    paths = export(populated_sheet, selected, {}, tmp_path, locale)

    wb = openpyxl.load_workbook(paths[0])
    ws = wb.active
    cell = ws.cell(row=2, column=2)
    assert isinstance(cell.value, (int, float))
    assert cell.value == 1234.56


def test_xlsx_export_number_format_german(populated_sheet, tmp_path):
    from shapes.sheets.renderer.xlsx.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    all_fields = parse_fields(sheet)
    selected = [f for f in all_fields if f.name in ("name", "amount")]
    locale = resolve_locale("de_DE")

    paths = export(populated_sheet, selected, {}, tmp_path, locale)

    wb = openpyxl.load_workbook(paths[0])
    ws = wb.active
    cell = ws.cell(row=2, column=2)
    assert cell.number_format == '#.##0,00'


def test_xlsx_export_empty_sheet(sheet_dir, tmp_path):
    """Empty state.sqlite produces headers-only file."""
    from shapes.sheets.renderer.xlsx.export import export

    rebuild_state(sheet_dir)
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    fields = parse_fields(sheet)
    locale = resolve_locale("en_US")

    paths = export(sheet_dir, fields, {}, tmp_path, locale)

    wb = openpyxl.load_workbook(paths[0])
    ws = wb.active
    assert ws.max_row == 1  # header only
    assert ws[1][0].font.bold


def test_xlsx_export_filtered_fields(populated_sheet, tmp_path):
    from shapes.sheets.renderer.xlsx.export import export

    sheet = yaml.safe_load((populated_sheet / "sheet.yaml").read_text())
    all_fields = parse_fields(sheet)
    selected = [f for f in all_fields if f.name in ("name", "status")]

    locale = resolve_locale("en_US")
    paths = export(populated_sheet, selected, {}, tmp_path, locale)

    wb = openpyxl.load_workbook(paths[0])
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    assert headers == ["Name", "Status"]
    assert ws.max_column == 2
