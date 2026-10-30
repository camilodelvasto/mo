"""End-to-end: exports.yaml -> command adapter -> CSV + XLSX files."""
import csv
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from shapes.sheets.src.rebuild import rebuild_state


def _load_adapter(name: str):
    adapter_path = (
        Path(__file__).resolve().parent.parent
        / "shapes" / "sheets" / "commands" / f"{name}.py"
    )
    spec = importlib.util.spec_from_file_location(f"sheets_{name}", adapter_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

openpyxl = pytest.importorskip("openpyxl")


@pytest.fixture
def full_corpus(corpus_root):
    """Corpus with populated sheet, exports.yaml, and locale."""
    sheet_dir = corpus_root / "content" / "test"

    # Add locale to moui.json
    manifest = json.loads((corpus_root / "moui.json").read_text())
    manifest["locale"] = "de_DE"
    (corpus_root / "moui.json").write_text(json.dumps(manifest, indent=2))

    # Add ops
    ops = [
        {
            "op": "insert", "ts": "2026-05-01T10:00:00Z", "id": "r001",
            "values": {"name": "Alice", "amount": 1234.56, "status": "new", "notes": "Test"},
        },
        {
            "op": "insert", "ts": "2026-05-02T11:00:00Z", "id": "r002",
            "values": {"name": "Bob", "amount": 7890.12, "status": "done", "notes": ""},
        },
    ]
    (sheet_dir / "ops.jsonl").write_text(
        "\n".join(json.dumps(o) for o in ops) + "\n"
    )
    rebuild_state(sheet_dir)

    # Write exports.yaml
    exports = {
        "exports": {
            "local": {"formats": ["csv", "xlsx"]},
            "partner": {
                "formats": ["csv"],
                "fields": ["name", "amount"],
                "locale": "en_US",
            },
        }
    }
    (sheet_dir / "exports.yaml").write_text(yaml.dump(exports, sort_keys=False))

    return corpus_root


def test_export_csv_and_xlsx(full_corpus, monkeypatch):
    monkeypatch.chdir(full_corpus)
    adapter = _load_adapter("export_cmd")
    adapter.run(full_corpus, "sheets", ["content/test", "local"])

    export_dir = full_corpus / "content" / "test" / "exports" / "local"
    csv_path = export_dir / "test.csv"
    xlsx_path = export_dir / "test.xlsx"
    assert csv_path.exists()
    assert xlsx_path.exists()

    # CSV uses corpus locale (de_DE) — semicolon delimiter
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert len(rows) == 3  # header + 2 rows
    headers = rows[0]
    amount_idx = headers.index("Amount (EUR)")
    assert rows[1][amount_idx] == "1.234,56"  # German format

    # XLSX has numeric values
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    assert ws.max_row == 3  # header + 2 rows


def test_export_filtered_with_locale_override(full_corpus, monkeypatch):
    monkeypatch.chdir(full_corpus)
    adapter = _load_adapter("export_cmd")
    adapter.run(full_corpus, "sheets", ["content/test", "partner"])

    export_dir = full_corpus / "content" / "test" / "exports" / "partner"
    csv_path = export_dir / "test.csv"
    assert csv_path.exists()

    # Partner export uses en_US locale — comma delimiter
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=","))
    assert rows[0] == ["Name", "Amount (EUR)"]  # only 2 columns
    assert rows[1] == ["Alice", "1,234.56"]  # US format


def test_export_dry_run_writes_nothing(full_corpus, monkeypatch, capsys):
    monkeypatch.chdir(full_corpus)
    adapter = _load_adapter("export_cmd")
    adapter.run(full_corpus, "sheets", ["content/test", "local", "-n"])

    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "de_DE" in out

    export_dir = full_corpus / "content" / "test" / "exports" / "local"
    assert not export_dir.exists()
