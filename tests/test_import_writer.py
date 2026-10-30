import csv
import json
from pathlib import Path

import pytest
import yaml

from shapes.sheets.src.writer import write_import


def _write_csv(rows: list[list[str]], tmp_path: Path) -> Path:
    p = tmp_path / "source.csv"
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)
    return p


def _base_analysis():
    return {
        "file": "source.csv",
        "row_count": 2,
        "columns": [
            {
                "header": "Name",
                "position": 0,
                "type": "string",
                "date_format": None,
                "nulls": 0,
                "unique_count": 2,
                "total_count": 2,
                "is_unique": True,
                "values": None,
                "samples": ["Alice", "Bob"],
                "looks_like_url": False,
                "max_length": 5,
                "malformed_count": 0,
            },
            {
                "header": "Age",
                "position": 1,
                "type": "integer",
                "date_format": None,
                "nulls": 0,
                "unique_count": 2,
                "total_count": 2,
                "is_unique": True,
                "values": None,
                "samples": ["30", "25"],
                "looks_like_url": False,
                "max_length": 2,
                "malformed_count": 0,
            },
        ],
    }


def _base_composer_output():
    return {
        "title": "People",
        "description": "A people sheet.",
        "header_map": {"Name": "name", "Age": "age"},
        "fields": {
            "id": "primary",
            "name": {"type": "string", "label": "Name"},
            "age": {"type": "integer", "label": "Age"},
            "created_at": "datetime",
            "updated_at": "datetime",
        },
        "pipeline": {
            "inputs": {
                "NEW": {
                    "prompt_template": "extract",
                    "op": "insert",
                    "key": "n",
                    "description": "Create from text",
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
        "view": {},
    }


def _data_rows():
    return [["Alice", "30"], ["Bob", "25"]]


def _headers():
    return ["Name", "Age"]


class TestWriteImport:
    def test_creates_sheet_yaml(self, tmp_path):
        target = tmp_path / "content" / "test" / "people"
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)
        (templates / "extract.md").write_text("extract template")

        write_import(
            target_dir=target,
            composer_output=_base_composer_output(),
            analysis=_base_analysis(),
            headers=_headers(),
            data_rows=_data_rows(),
            templates_dir=templates,
        )

        sheet = yaml.safe_load((target / "sheet.yaml").read_text())
        assert sheet["title"] == "People"
        assert sheet["instance"] == "sheets"
        assert "fields" in sheet
        assert "pipeline" in sheet

    def test_creates_ops_jsonl(self, tmp_path):
        target = tmp_path / "content" / "test" / "people"
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)
        (templates / "extract.md").write_text("extract template")

        write_import(
            target_dir=target,
            composer_output=_base_composer_output(),
            analysis=_base_analysis(),
            headers=_headers(),
            data_rows=_data_rows(),
            templates_dir=templates,
        )

        ops = (target / "ops.jsonl").read_text().strip().splitlines()
        assert len(ops) == 2
        first = json.loads(ops[0])
        assert first["op"] == "insert"
        assert first["values"]["name"] == "Alice"
        assert first["values"]["age"] == "30"
        assert first["id"].startswith("r")
        assert len(first["id"]) == 15  # r + 14 digits

    def test_row_ids_are_unique_and_ordered(self, tmp_path):
        target = tmp_path / "content" / "test" / "people"
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)
        (templates / "extract.md").write_text("extract template")

        write_import(
            target_dir=target,
            composer_output=_base_composer_output(),
            analysis=_base_analysis(),
            headers=_headers(),
            data_rows=_data_rows(),
            templates_dir=templates,
        )

        ops = [json.loads(line) for line in (target / "ops.jsonl").read_text().strip().splitlines()]
        ids = [op["id"] for op in ops]
        assert len(set(ids)) == len(ids)
        assert ids == sorted(ids)

    def test_creates_exports_yaml(self, tmp_path):
        target = tmp_path / "content" / "test" / "people"
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)
        (templates / "extract.md").write_text("extract template")

        write_import(
            target_dir=target,
            composer_output=_base_composer_output(),
            analysis=_base_analysis(),
            headers=_headers(),
            data_rows=_data_rows(),
            templates_dir=templates,
        )

        exports = yaml.safe_load((target / "exports.yaml").read_text())
        assert "exports" in exports
        assert "local" in exports["exports"]

    def test_copies_prompt_templates(self, tmp_path):
        target = tmp_path / "content" / "test" / "people"
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)
        (templates / "extract.md").write_text("extract template content")

        write_import(
            target_dir=target,
            composer_output=_base_composer_output(),
            analysis=_base_analysis(),
            headers=_headers(),
            data_rows=_data_rows(),
            templates_dir=templates,
        )

        assert (target / "prompts" / "extract.md").exists()
        assert (target / "prompts" / "extract.md").read_text() == "extract template content"

    def test_creates_ingest_dirs(self, tmp_path):
        target = tmp_path / "content" / "test" / "people"
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)
        (templates / "extract.md").write_text("extract template")

        write_import(
            target_dir=target,
            composer_output=_base_composer_output(),
            analysis=_base_analysis(),
            headers=_headers(),
            data_rows=_data_rows(),
            templates_dir=templates,
        )

        assert (target / "ingest" / "inbox").is_dir()
        assert (target / "ingest" / "staging").is_dir()
        assert (target / "ingest" / "failed").is_dir()

    def test_throws_if_target_exists(self, tmp_path):
        target = tmp_path / "content" / "test" / "people"
        target.mkdir(parents=True)
        (target / "sheet.yaml").write_text("existing")
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)

        with pytest.raises(FileExistsError):
            write_import(
                target_dir=target,
                composer_output=_base_composer_output(),
                analysis=_base_analysis(),
                headers=_headers(),
                data_rows=_data_rows(),
                templates_dir=templates,
            )

    def test_null_mapped_columns_skipped(self, tmp_path):
        target = tmp_path / "content" / "test" / "people"
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)
        (templates / "extract.md").write_text("extract template")

        output = _base_composer_output()
        output["header_map"]["Age"] = None
        del output["fields"]["age"]

        write_import(
            target_dir=target,
            composer_output=output,
            analysis=_base_analysis(),
            headers=_headers(),
            data_rows=_data_rows(),
            templates_dir=templates,
        )

        ops = [json.loads(line) for line in (target / "ops.jsonl").read_text().strip().splitlines()]
        assert "age" not in ops[0]["values"]

    def test_pipeline_prompt_rewritten_to_path(self, tmp_path):
        target = tmp_path / "content" / "test" / "people"
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)
        (templates / "extract.md").write_text("extract template")

        write_import(
            target_dir=target,
            composer_output=_base_composer_output(),
            analysis=_base_analysis(),
            headers=_headers(),
            data_rows=_data_rows(),
            templates_dir=templates,
        )

        sheet = yaml.safe_load((target / "sheet.yaml").read_text())
        new_input = sheet["pipeline"]["inputs"]["NEW"]
        assert new_input["prompt"] == "prompts/extract.md"
        assert "prompt_template" not in new_input

    def test_date_coercion_to_iso(self, tmp_path):
        target = tmp_path / "content" / "test" / "dates"
        templates = tmp_path / "templates" / "prompts"
        templates.mkdir(parents=True)
        (templates / "extract.md").write_text("extract template")

        analysis = {
            "file": "dates.csv",
            "row_count": 2,
            "columns": [
                {
                    "header": "Date",
                    "position": 0,
                    "type": "date",
                    "date_format": "%d.%m.%Y",
                    "nulls": 0,
                    "unique_count": 2,
                    "total_count": 2,
                    "is_unique": True,
                    "values": None,
                    "samples": ["15.01.2024", "28.02.2024"],
                    "looks_like_url": False,
                    "max_length": 10,
                    "malformed_count": 0,
                },
            ],
        }
        output = {
            "title": "Dates",
            "header_map": {"Date": "event_date"},
            "fields": {
                "id": "primary",
                "event_date": {"type": "date", "label": "Event Date"},
                "created_at": "datetime",
                "updated_at": "datetime",
            },
            "pipeline": {
                "inputs": {
                    "NEW": {
                        "prompt_template": "extract",
                        "op": "insert",
                        "key": "n",
                        "description": "Create",
                    },
                    "SET": {
                        "bypass_inference": True,
                        "op": "update",
                        "key": "e",
                        "description": "Edit",
                        "context": {"row_id": "required", "cell": "required"},
                    },
                }
            },
            "keys": {"view": "v", "search": "/", "toggle_hidden": "H", "open": "o"},
            "view": {},
        }

        write_import(
            target_dir=target,
            composer_output=output,
            analysis=analysis,
            headers=["Date"],
            data_rows=[["15.01.2024"], ["28.02.2024"]],
            templates_dir=templates,
        )

        ops = [json.loads(l) for l in (target / "ops.jsonl").read_text().strip().splitlines()]
        assert ops[0]["values"]["event_date"] == "2024-01-15"
        assert ops[1]["values"]["event_date"] == "2024-02-28"
