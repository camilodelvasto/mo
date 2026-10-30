# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the import command adapter."""
import csv
import json
from pathlib import Path
from unittest.mock import patch
import pytest
import yaml


def _write_csv(rows, path):
    p = path / "source.csv"
    with open(p, "w", newline="") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)
    return p


def _setup_corpus(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "moui.json").write_text(json.dumps({
        "name": "test-corpus",
        "inference": {"default": "claude"},
    }))
    (corpus / "content" / "test").mkdir(parents=True)
    return corpus


def _mock_composer_output():
    return {
        "title": "People",
        "description": "Imported people.",
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


class TestImportCommand:
    @patch("shapes.sheets.src.validator.validate_composer_output")
    @patch("shapes.sheets.src.composer.run_composer")
    def test_full_pipeline(self, mock_composer, mock_validator, tmp_path):
        mock_composer.return_value = _mock_composer_output()
        mock_validator.return_value = None
        corpus = _setup_corpus(tmp_path)
        csv_path = _write_csv([
            ["Name", "Age"],
            ["Alice", "30"],
            ["Bob", "25"],
        ], tmp_path)

        # Create template files the writer expects to copy
        from shapes.sheets.commands.import_cmd import run
        shape_root = Path(__file__).resolve().parent.parent / "shapes" / "sheets"
        templates_dir = shape_root / "templates" / "prompts"
        templates_dir.mkdir(parents=True, exist_ok=True)
        extract_md = templates_dir / "extract.md"
        created_extract = False
        if not extract_md.exists():
            extract_md.write_text("extract prompt template")
            created_extract = True

        try:
            run(corpus, "sheets", [str(csv_path), "--corpus", "test", "--name", "people"])
        finally:
            if created_extract:
                extract_md.unlink(missing_ok=True)

        target = corpus / "content" / "test" / "people"
        assert (target / "sheet.yaml").exists()
        assert (target / "ops.jsonl").exists()
        assert (target / "exports.yaml").exists()
        assert (target / "state.sqlite").exists()

        sheet = yaml.safe_load((target / "sheet.yaml").read_text())
        assert sheet["title"] == "People"
        assert sheet["instance"] == "sheets"

        ops = (target / "ops.jsonl").read_text().strip().splitlines()
        assert len(ops) == 2

    @patch("shapes.sheets.src.composer.run_composer")
    def test_throws_on_existing_dir(self, mock_composer, tmp_path):
        mock_composer.return_value = _mock_composer_output()
        corpus = _setup_corpus(tmp_path)
        csv_path = _write_csv([["Name"], ["Alice"]], tmp_path)

        target = corpus / "content" / "test" / "people"
        target.mkdir(parents=True)
        (target / "sheet.yaml").write_text("existing")

        from shapes.sheets.commands.import_cmd import run
        with pytest.raises(SystemExit):
            run(corpus, "sheets", [str(csv_path), "--corpus", "test", "--name", "people"])
