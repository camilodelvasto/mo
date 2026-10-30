import json
from pathlib import Path
import pytest
from shapes.sheets.src.composer import build_composer_prompt, parse_composer_response


class TestBuildComposerPrompt:
    def test_prompt_contains_analysis(self):
        prompt = build_composer_prompt(
            analysis={"file": "test.csv", "row_count": 100, "columns": [{"header": "Name", "looks_like_url": False}]},
            sheet_name="contacts",
            corpus_name="work",
            schema_text="{}",
            field_options_text="field options here",
            pipeline_reference_text="pipeline reference here",
            template_list=["extract.md — extract from text", "update.md — update row"],
        )
        assert "Name" in prompt
        assert "contacts" in prompt

    def test_prompt_contains_schema(self):
        prompt = build_composer_prompt(
            analysis={"file": "t.csv", "row_count": 1, "columns": []},
            sheet_name="x", corpus_name="y",
            schema_text='{"title": "Sheet Definition"}',
            field_options_text="opts", pipeline_reference_text="pipe",
            template_list=["extract.md — extract"],
        )
        assert "Sheet Definition" in prompt

    def test_prompt_contains_template_list(self):
        prompt = build_composer_prompt(
            analysis={"file": "t.csv", "row_count": 1, "columns": []},
            sheet_name="x", corpus_name="y",
            schema_text="{}", field_options_text="opts", pipeline_reference_text="pipe",
            template_list=["extract.md — extract from text", "update.md — update row"],
        )
        assert "extract.md" in prompt
        assert "update.md" in prompt


class TestParseComposerResponse:
    def test_parses_valid_json(self):
        response = json.dumps({
            "title": "Contacts",
            "header_map": {"Name": "name"},
            "fields": {"id": "primary", "name": "string"},
            "pipeline": {"inputs": {}},
            "keys": {},
            "view": {},
        })
        result = parse_composer_response(response)
        assert result["title"] == "Contacts"

    def test_raises_on_missing_required_keys(self):
        response = json.dumps({"title": "Contacts"})
        with pytest.raises(ValueError, match="header_map"):
            parse_composer_response(response)

    def test_extracts_json_from_markdown_fence(self):
        response = "Here's the output:\n```json\n" + json.dumps({
            "title": "X",
            "header_map": {},
            "fields": {"id": "primary"},
            "pipeline": {"inputs": {}},
            "keys": {},
            "view": {},
        }) + "\n```\nDone."
        result = parse_composer_response(response)
        assert result["title"] == "X"
