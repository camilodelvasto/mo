import json
import os

import pytest
import yaml

from shapes.sheets.src.inference import resolve_backend


def test_resolve_from_moui_json(corpus_root):
    backend, model = resolve_backend(corpus_root)
    assert backend == "ollama"
    assert model == "qwen3:8b"


def test_resolve_sheet_overrides_corpus(corpus_root):
    sheet_dir = corpus_root / "content" / "test"
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet["inference"] = {"default": {"backend": "claude", "model": "default"}}
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))

    backend, model = resolve_backend(corpus_root, sheet_dir=sheet_dir)
    assert backend == "claude"
    assert model == "default"


def test_resolve_env_var_overrides_all(corpus_root, monkeypatch):
    monkeypatch.setenv("SHEETS_LLM", "anthropic")
    backend, model = resolve_backend(corpus_root)
    assert backend == "anthropic"
    assert model == "default"


def test_resolve_env_var_with_model(corpus_root, monkeypatch):
    monkeypatch.setenv("SHEETS_LLM", "anthropic:claude-sonnet-4-20250514")
    backend, model = resolve_backend(corpus_root)
    assert backend == "anthropic"
    assert model == "claude-sonnet-4-20250514"


def test_resolve_raises_when_no_config(tmp_path):
    manifest = {"v": 1, "name": "bare", "shapes": ["sheets"]}
    (tmp_path / "moui.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="No inference backend configured"):
        resolve_backend(tmp_path)
