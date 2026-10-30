# tests/test_corpus_query_cmd.py
import io
import json
from pathlib import Path

import pytest
import yaml

from shapes.corpus.commands import query


def _corpus(tmp_path):
    c = tmp_path / "corp"; c.mkdir()
    (c / "corpus.yaml").write_text(yaml.safe_dump(
        {"id": "c", "flow": "./flow.yaml", "queries": "./queries"}))
    return c


def test_manifest_declares_query_verb():
    shape = Path(__file__).resolve().parents[1] / "shapes" / "corpus"
    manifest = yaml.safe_load((shape / "shape.manifest.yaml").read_text())
    assert manifest["capabilities"]["query"][0]["adapter"] == "commands/query.py"
    assert (shape / "commands" / "query.py").is_file()


def test_save_definition_only(tmp_path, capsys):
    c = _corpus(tmp_path)
    query.run(tmp_path, "corpus", [
        "save", str(c), "esi", "--ask", "answer", "--question", "¿educación?",
        "--grounding", "1.0", "--mode", "hybrid", "--definition-only"])
    saved = (c / "queries" / "esi.md").read_text()
    front = yaml.safe_load(saved.split("---\n")[1])
    assert front["ask"] == "answer" and front["question"] == "¿educación?"
    assert saved.split("---\n", 2)[2].strip() == ""        # no body


def test_save_with_record_from_stdin(tmp_path, monkeypatch):
    c = _corpus(tmp_path)
    record = {"ask": "answer", "question": "¿q?", "answer": "Sí. [aaaaaaaaaaaa:r1]",
              "passages": [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "x",
                            "score": 0.4, "retriever": "hybrid", "span": [0, 1],
                            "name": "doc.md"}]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(record)))
    query.run(tmp_path, "corpus", [
        "save", str(c), "esi", "--ask", "answer", "--question", "¿q?",
        "--grounding", "1.0", "--mode", "hybrid"])
    assert "Sí. [aaaaaaaaaaaa:r1]" in (c / "queries" / "esi.md").read_text()   # answer verbatim


def test_list_json(tmp_path, capsys):
    c = _corpus(tmp_path)
    query.run(tmp_path, "corpus", [
        "save", str(c), "esi", "--ask", "answer", "--question", "¿educación?",
        "--grounding", "1.0", "--mode", "hybrid", "--definition-only"])
    capsys.readouterr()
    query.run(tmp_path, "corpus", ["list", str(c), "--json"])
    items = json.loads(capsys.readouterr().out)
    assert items[0]["name"] == "esi" and items[0]["ask"] == "answer"


def test_save_missing_required_flag_throws(tmp_path):
    c = _corpus(tmp_path)
    with pytest.raises(SystemExit):
        query.run(tmp_path, "corpus", ["save", str(c), "esi", "--ask", "answer"])


def test_save_rejects_out_of_range_grounding(tmp_path):
    c = _corpus(tmp_path)
    with pytest.raises(SystemExit):
        query.run(tmp_path, "corpus", [
            "save", str(c), "esi", "--ask", "answer", "--question", "¿q?",
            "--grounding", "99", "--mode", "hybrid", "--definition-only"])


def test_save_dangling_flag_raises_systemexit(tmp_path):
    c = _corpus(tmp_path)
    with pytest.raises(SystemExit):
        query.run(tmp_path, "corpus", ["save", str(c), "esi", "--ask"])
