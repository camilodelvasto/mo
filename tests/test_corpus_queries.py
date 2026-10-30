# tests/test_corpus_queries.py
from pathlib import Path

import pytest
import yaml

from shapes.corpus.access import queries
from shapes.corpus.access.queries import QueriesError


def _corpus(tmp_path, declare=True):
    c = tmp_path / "corp"; c.mkdir()
    doc = {"id": "c", "flow": "./flow.yaml"}
    if declare:
        doc["queries"] = "./queries"
    (c / "corpus.yaml").write_text(yaml.safe_dump(doc))
    return c


_DEF = {"ask": "answer", "question": "¿educación?", "grounding": 1.0,
        "mode": "hybrid", "where": None, "saved": "2026-06-14T10:30:00"}
_RECORD = {"ask": "answer", "question": "¿educación?", "answer": "Sí. [aaaaaaaaaaaa:r1]",
           "passages": [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "esi",
                         "score": 0.4, "retriever": "hybrid", "span": [0, 3],
                         "name": "estudio-esi.md"}]}


def test_queries_dir_throws_when_undeclared(tmp_path):
    with pytest.raises(QueriesError):
        queries.queries_dir(_corpus(tmp_path, declare=False))


def test_save_definition_only_writes_frontmatter_empty_body(tmp_path):
    c = _corpus(tmp_path)
    path = queries.save_query(c, "esi", _DEF, record=None)
    assert path.name == "esi.md"
    front = yaml.safe_load(path.read_text().split("---\n")[1])
    assert front["ask"] == "answer" and front["question"] == "¿educación?"
    assert front["grounding"] == 1.0
    body = path.read_text().split("---\n", 2)[2].strip()
    assert body == ""                              # definition-only: no result


def test_save_with_record_writes_answer_body(tmp_path):
    c = _corpus(tmp_path)
    path = queries.save_query(c, "esi", _DEF, record=_RECORD)
    text = path.read_text()
    assert "Sí. [aaaaaaaaaaaa:r1]" in text          # the answer verbatim — no renumber
    assert "— sources —" not in text                # no renderer-appended source list


def test_list_round_trips_saved_definitions(tmp_path):
    c = _corpus(tmp_path)
    queries.save_query(c, "esi", _DEF, record=None)
    items = queries.list_queries(c)
    assert len(items) == 1
    assert items[0]["name"] == "esi"
    assert items[0]["ask"] == "answer"
    assert items[0]["question"] == "¿educación?"


def test_list_is_empty_when_folder_absent_but_declared(tmp_path):
    assert queries.list_queries(_corpus(tmp_path)) == []


_RECORD_PROV = {
    "ask": "answer", "question": "¿educación?", "answer": "Sí. [aaaaaaaaaaaa:r1]",
    "passages": [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "esi", "score": 0.4,
                  "retriever": "hybrid", "span": [0, 3], "name": "estudio-esi.md"}],
    "provenance": {"model": "claude-opus-4-8", "cost_usd": 0.046,
                   "usage": {"input_tokens": 1234, "output_tokens": 480,
                             "cache_read_input_tokens": 21434},
                   "retrieval_ms": 312, "synthesis_ms": 4103, "total_ms": 4421,
                   "prompt": "GROUNDING 1.0\n\nPregunta: ¿educación?"},
}


def test_save_with_provenance_writes_frontmatter_and_prompt_body(tmp_path):
    c = _corpus(tmp_path)
    path = queries.save_query(c, "esi", _DEF, record=_RECORD_PROV)
    text = path.read_text()
    front = yaml.safe_load(text.split("---\n")[1])
    assert front["model"] == "claude-opus-4-8"
    assert front["input_tokens"] == 1234 and front["output_tokens"] == 480
    assert front["cost_usd"] == 0.046
    assert front["retrieval_ms"] == 312 and front["total_ms"] == 4421
    assert "— how this was produced —" in text
    assert "Pregunta: ¿educación?" in text          # the full prompt is in the body
