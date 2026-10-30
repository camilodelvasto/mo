import json
import shutil

import pytest
import yaml


@pytest.fixture
def sheet_dir(tmp_path_factory):
    """Create a minimal sheet directory for testing."""
    tmp_path = tmp_path_factory.mktemp("sheet")
    sheet = {
        "title": "Test Sheet",
        "pipeline": {
            "inputs": {
                "NEW": {
                    "prompt": "prompts/extract.md",
                    "op": "insert",
                    "key": "n",
                    "description": "Create from text",
                },
                "UPDATE": {
                    "prompt": "prompts/update.md",
                    "op": "update",
                    "key": "l",
                    "description": "Log entry",
                    "context": {"row_id": "required"},
                },
                "FETCH": {
                    "preprocess": "trafilatura",
                    "prompt": "prompts/extract.md",
                    "op": "insert",
                    "key": "f",
                    "description": "Create from URL",
                },
                "SET": {
                    "bypass_inference": True,
                    "op": "update",
                    "key": "e",
                    "description": "Edit cell",
                    "context": {"row_id": "required", "cell": "required"},
                },
                "LOG": {
                    "op": "append",
                    "target_field": "activity",
                    "key": "a",
                    "description": "Log entry",
                    "context": {"row_id": "required"},
                },
            }
        },
        "fields": {
            "id": "primary",
            "created_at": "datetime",
            "updated_at": "datetime",
            "name": "string",
            "amount": {
                "type": "number",
                "label": "Amount (EUR)",
                "width": 10,
                "align": "right",
            },
            "status": "enum [new, done]",
            "notes": "text",
            "starred": {
                "type": "boolean",
                "label": "★",
                "width": 3,
                "key": "s",
            },
            "hidden": {
                "type": "boolean",
                "label": "×",
                "width": 3,
                "key": "x",
            },
            "activity": {
                "type": "log",
                "label": "Activity",
            },
        },
    }
    (tmp_path / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))
    (tmp_path / "ops.jsonl").write_text("")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "extract.md").write_text(
        "Extract fields from the text.\n\n## Fields\n{{schema}}\n\n## Text\n{{body}}\n\n"
        "Return JSON with extracted fields only."
    )
    (prompts / "update.md").write_text(
        "Update row based on entry.\n\n## Current state\n{{row}}\n\n## Entry\n{{body}}\n\n"
        "## Time\n{{now}}\n\n## Fields\n{{schema}}\n\nReturn JSON with changed fields only."
    )
    ingest = tmp_path / "ingest"
    inbox = ingest / "inbox"
    inbox.mkdir(parents=True)
    (ingest / "failed").mkdir()
    (ingest / "staging").mkdir()
    (ingest / "journal.jsonl").write_text("")
    return tmp_path


@pytest.fixture
def corpus_root(tmp_path, sheet_dir):
    """Create a corpus root with moui.json and a test sheet in content/."""
    content_dir = tmp_path / "content" / "test"
    content_dir.parent.mkdir(parents=True, exist_ok=True)
    if content_dir.exists():
        shutil.rmtree(content_dir)
    shutil.copytree(sheet_dir, content_dir)

    manifest = {
        "v": 1,
        "name": "test-corpus",
        "shapes": {
            "sheets": {"shape": "sheets", "version": "0.1.0", "local": True}
        },
        "inference": {"default": {"backend": "ollama", "model": "qwen3:8b"}},
    }
    (tmp_path / "moui.json").write_text(json.dumps(manifest))
    return tmp_path
