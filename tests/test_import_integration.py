# tests/test_import_integration.py
"""End-to-end import integration test with mocked LLM."""
import csv
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from shapes.sheets.src.analyzer import analyze_file, _read_csv
from shapes.sheets.src.validator import validate_composer_output
from shapes.sheets.src.writer import write_import
from shapes.sheets.src.rebuild import rebuild_state


def _write_csv(rows, tmp_path):
    p = tmp_path / "products.csv"
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)
    return p


PRODUCTS_CSV = [
    ["SKU", "Product Name", "Price", "Category", "In Stock", "Launch Date", "URL"],
    ["SKU-001", "Widget A", "29.99", "widgets", "true", "2024-01-15", "https://example.com/a"],
    ["SKU-002", "Widget B", "49.99", "widgets", "false", "2024-02-20", "https://example.com/b"],
    ["SKU-003", "Gadget X", "99.50", "gadgets", "true", "2024-03-10", "https://example.com/x"],
    ["SKU-004", "Gadget Y", "149.00", "gadgets", "true", "2024-04-01", "https://example.com/y"],
    ["SKU-005", "Doohickey", "9.99", "accessories", "false", "2024-05-15", "https://example.com/d"],
    ["SKU-006", "Widget C", "34.99", "widgets", "true", "2024-06-01", "https://example.com/c"],
    ["SKU-007", "Gadget Z", "119.00", "gadgets", "false", "2024-07-12", "https://example.com/z"],
]

COMPOSER_OUTPUT = {
    "title": "Product Catalog",
    "description": "Imported product catalog.",
    "header_map": {
        "SKU": "sku",
        "Product Name": "product_name",
        "Price": "price",
        "Category": "category",
        "In Stock": "in_stock",
        "Launch Date": "launch_date",
        "URL": "url",
    },
    "fields": {
        "id": "primary",
        "sku": {"type": "string", "label": "SKU", "width": 10},
        "product_name": {"type": "string", "label": "Product Name"},
        "price": {"type": "number", "label": "Price", "align": "right"},
        "category": {
            "type": "enum",
            "values": ["accessories", "gadgets", "widgets"],
            "label": "Category",
        },
        "in_stock": {"type": "boolean", "label": "In Stock", "key": "s", "width": 3},
        "launch_date": {"type": "date", "label": "Launch Date"},
        "url": {"type": "string", "label": "URL", "action": "open"},
        "created_at": "datetime",
        "updated_at": "datetime",
        "notes": {"type": "text", "label": "Notes"},
    },
    "pipeline": {
        "inputs": {
            "NEW": {
                "prompt_template": "extract",
                "op": "insert",
                "key": "n",
                "description": "Create from text",
            },
            "FETCH": {
                "prompt_template": "extract",
                "op": "insert",
                "key": "f",
                "description": "Create from URL",
                "preprocess": "trafilatura",
            },
            "UPDATE": {
                "prompt_template": "update",
                "op": "update",
                "key": "u",
                "description": "Smart update",
                "context": {"row_id": "required"},
            },
            "SET": {
                "bypass_inference": True,
                "op": "update",
                "key": "e",
                "description": "Edit cell",
                "context": {"row_id": "required", "cell": "required"},
            },
        }
    },
    "keys": {"view": "v", "search": "/", "toggle_hidden": "H", "open": "o"},
    "view": {"notes_field": "notes"},
}


class TestImportIntegration:
    def test_full_pipeline(self, tmp_path):
        # Write source CSV
        csv_path = _write_csv(PRODUCTS_CSV, tmp_path)

        # Set up templates dir
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)
        (templates / "extract.md").write_text(
            "Extract structured data from the text below.\n\n## Fields\n{{schema}}\n\n## Text\n{{body}}"
        )
        (templates / "update.md").write_text(
            "Update the existing row.\n\n## Current state\n{{row}}\n\n## Entry\n{{body}}"
        )

        target = tmp_path / "content" / "work" / "products"

        # Phase 1: Analyze
        analysis = analyze_file(csv_path)
        assert analysis["row_count"] == 7
        assert len(analysis["columns"]) == 7

        # Verify analyzer detected key properties
        sku_col = analysis["columns"][0]
        assert sku_col["is_unique"] is True

        price_col = analysis["columns"][2]
        assert price_col["type"] == "number"

        category_col = analysis["columns"][3]
        assert category_col["values"] is not None
        assert set(category_col["values"]) == {"accessories", "gadgets", "widgets"}

        stock_col = analysis["columns"][4]
        assert stock_col["type"] == "boolean"

        date_col = analysis["columns"][5]
        assert date_col["type"] == "date"
        assert date_col["date_format"] == "%Y-%m-%d"

        url_col = analysis["columns"][6]
        assert url_col["looks_like_url"] is True

        # Phase 3: Validate
        validate_composer_output(COMPOSER_OUTPUT, analysis, templates)

        # Phase 4: Write
        headers, data_rows = _read_csv(csv_path)
        report = write_import(
            target_dir=target,
            composer_output=COMPOSER_OUTPUT,
            analysis=analysis,
            headers=headers,
            data_rows=data_rows,
            templates_dir=templates,
        )

        assert report["row_count"] == 7
        assert report["column_count"] == 7

        # Verify sheet.yaml
        sheet = yaml.safe_load((target / "sheet.yaml").read_text())
        assert sheet["instance"] == "sheets"
        assert sheet["title"] == "Product Catalog"
        assert sheet["fields"]["category"]["type"] == "enum"
        assert sheet["pipeline"]["inputs"]["NEW"]["prompt"] == "prompts/extract.md"
        assert "prompt_template" not in sheet["pipeline"]["inputs"]["NEW"]

        # Verify ops.jsonl
        ops = [json.loads(l) for l in (target / "ops.jsonl").read_text().strip().splitlines()]
        assert len(ops) == 7
        assert ops[0]["values"]["sku"] == "SKU-001"
        assert ops[0]["values"]["price"] == "29.99"
        assert ops[0]["values"]["in_stock"] == "true"
        ids = [op["id"] for op in ops]
        assert ids == sorted(ids)
        assert len(set(ids)) == 7

        # Verify exports.yaml
        exports = yaml.safe_load((target / "exports.yaml").read_text())
        assert "local" in exports["exports"]

        # Verify prompts copied
        assert (target / "prompts" / "extract.md").exists()
        assert (target / "prompts" / "update.md").exists()

        # Verify ingest dirs
        assert (target / "ingest" / "inbox").is_dir()
        assert (target / "ingest" / "staging").is_dir()
        assert (target / "ingest" / "failed").is_dir()

        # Phase 5: Rebuild
        rebuild_state(target)
        assert (target / "state.sqlite").exists()

        # Verify SQLite content
        conn = sqlite3.connect(str(target / "state.sqlite"))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM rows ORDER BY id").fetchall()
        assert len(rows) == 7
        assert rows[0]["sku"] == "SKU-001"
        assert rows[0]["product_name"] == "Widget A"
        conn.close()
