import json
from pathlib import Path

import yaml

from shapes.sheets.src.scaffold import scaffold_sheet


def test_scaffold_creates_directory(corpus_root):
    target = corpus_root / "content" / "new-sheet"
    scaffold_sheet(target, corpus_root)
    assert target.exists()
    assert (target / "sheet.yaml").exists()
    assert (target / "prompts" / "extract.md").exists()
    assert (target / "prompts" / "update.md").exists()
    assert (target / "ops.jsonl").exists()
    assert (target / "ingest" / "inbox").is_dir()
    assert (target / "ingest" / "failed").is_dir()
    assert (target / "ingest" / "journal.jsonl").exists()
    assert (target / ".gitignore").exists()


def test_scaffold_fills_template_variables(corpus_root):
    target = corpus_root / "content" / "my-project"
    scaffold_sheet(target, corpus_root)
    sheet = yaml.safe_load((target / "sheet.yaml").read_text())
    assert sheet["title"] == "My Project"
    assert "pipeline" in sheet
    assert "fields" in sheet


def test_scaffold_does_not_modify_moui_json(corpus_root):
    """Scaffold creates the directory but does NOT modify moui.json.
    Content is self-describing, not registered in the corpus manifest."""
    import json
    original = (corpus_root / "moui.json").read_text()
    target = corpus_root / "content" / "new-sheet"
    scaffold_sheet(target, corpus_root)
    after = (corpus_root / "moui.json").read_text()
    assert original == after


def test_scaffold_rejects_existing_nonempty_dir(corpus_root):
    target = corpus_root / "content" / "existing"
    target.mkdir(parents=True)
    (target / "somefile.txt").write_text("occupied")

    import pytest
    with pytest.raises(SystemExit):
        scaffold_sheet(target, corpus_root)


def test_scaffold_validates_result(corpus_root):
    target = corpus_root / "content" / "valid-sheet"
    scaffold_sheet(target, corpus_root)
    sheet = yaml.safe_load((target / "sheet.yaml").read_text())
    assert "title" in sheet
    assert "pipeline" in sheet
    assert "inputs" in sheet["pipeline"]
    assert "fields" in sheet


def test_scaffold_creates_exports_yaml(corpus_root):
    target = corpus_root / "content" / "export-sheet"
    scaffold_sheet(target, corpus_root)
    exports_path = target / "exports.yaml"
    assert exports_path.exists()
    content = yaml.safe_load(exports_path.read_text())
    assert "exports" in content
    assert "local" in content["exports"]
    assert content["exports"]["local"]["formats"] == ["csv", "xlsx"]


def test_scaffold_gitignore_includes_exports(corpus_root):
    target = corpus_root / "content" / "gitignore-sheet"
    scaffold_sheet(target, corpus_root)
    gitignore = (target / ".gitignore").read_text()
    assert "exports/" in gitignore
