# tests/test_corpus_access_format.py
from shapes.corpus.commands._access_cli import format_answer, format_passages

_PASSAGES = [
    {"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "educación sexual integral",
     "score": 0.42, "retriever": "hybrid", "span": [0, 24], "name": "estudio-esi.md"},
]


def test_format_passages_shows_tiny_hash_and_name():
    out = format_passages(_PASSAGES)
    assert "aaaaaaaa" in out                     # the tiny content-hash (8 chars)
    assert "aaaaaaaaaaaa" not in out             # NOT the full 12-char hash
    assert "estudio-esi.md" in out               # the document name
    assert "educación sexual integral" in out    # the snippet


def test_format_answer_returns_the_answer_verbatim():
    # the reader view is the model's answer as written — no citation renumbering, no
    # renderer-appended source list. Sources are the prompt's business (${sources}).
    record = {"ask": "answer", "question": "¿q?",
              "answer": "Sí [aaaaaaaaaaaa:r1] y también [aaaaaaaaaaaa:r2].",
              "passages": _PASSAGES}
    out = format_answer(record)
    assert out == "Sí [aaaaaaaaaaaa:r1] y también [aaaaaaaaaaaa:r2]."   # verbatim
    assert "— sources —" not in out                                    # nothing appended


def test_format_answer_no_markers_is_the_plain_answer():
    out = format_answer({"answer": "Respuesta sin citas.", "passages": []})
    assert out == "Respuesta sin citas."


_PROV = {"model": "claude-opus-4-8", "cost_usd": 0.046,
         "usage": {"input_tokens": 1234, "output_tokens": 480, "cache_read_input_tokens": 21434},
         "retrieval_ms": 312, "synthesis_ms": 4103, "total_ms": 4421,
         "prompt": "Source-grounding level: 1.0 …\n\nPregunta: ¿q?"}


def test_format_provenance_shows_model_tokens_cost_timing_and_prompt():
    from shapes.corpus.commands._access_cli import format_provenance
    out = format_provenance(_PROV)
    assert "claude-opus-4-8" in out
    assert "1234 in / 480 out" in out
    assert "$0.0460" in out
    assert "retrieval 312ms" in out and "synthesis 4103ms" in out and "total 4421ms" in out
    assert "— prompt —" in out and "Pregunta: ¿q?" in out


def test_format_provenance_find_has_timing_only():
    from shapes.corpus.commands._access_cli import format_provenance
    out = format_provenance({"retrieval_ms": 5, "total_ms": 6})
    assert "retrieval 5ms" in out and "total 6ms" in out
    assert "model" not in out and "— prompt —" not in out
