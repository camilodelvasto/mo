from pathlib import Path

from shapes.corpus.access import index, retrieve


def _seed(tmp_path):
    corpus = tmp_path / "c"; corpus.mkdir()
    conn = index.open_index(corpus, dim=3)
    rows = [
        ("d1", "r1", "educación sexual en colegios", [1.0, 0.0, 0.0]),
        ("d1", "r2", "política pública", [0.0, 1.0, 0.0]),
        ("d2", "r3", "educación y familia", [0.9, 0.1, 0.0]),
    ]
    for i, (doc, ref, text, vec) in enumerate(rows, start=1):
        conn.execute("INSERT INTO chunks(rowid, doc_id, ref, span_start, span_end, text) "
                     "VALUES (?,?,?,?,?,?)", (i, doc, ref, 0, len(text), text))
        conn.execute("INSERT INTO vec_chunks(rowid, doc_id, embedding) VALUES (?,?,?)",
                     (i, doc, index.serialize(vec)))
        conn.execute("INSERT INTO fts_chunks(rowid, text) VALUES (?,?)", (i, text))
    conn.commit()
    return conn


def _embed(text):  # query embed: nearest to "educación" cluster
    return [1.0, 0.0, 0.0]


def test_vector_mode_ranks_by_distance(tmp_path):
    conn = _seed(tmp_path)
    hits = retrieve.retrieve(conn, "vector", k=2, scope=None, question="educación", embed=_embed)
    assert [h["ref"] for h in hits] == ["r1", "r3"]
    assert hits[0]["retriever"] == "vector"
    assert hits[0]["span"] == [0, len("educación sexual en colegios")]


def test_lexical_mode_matches_terms(tmp_path):
    conn = _seed(tmp_path)
    hits = retrieve.retrieve(conn, "lexical", k=5, scope=None, question="política", embed=_embed)
    assert [h["ref"] for h in hits] == ["r2"]
    assert hits[0]["retriever"] == "lexical"


def test_scope_restricts_at_source(tmp_path):
    conn = _seed(tmp_path)
    hits = retrieve.retrieve(conn, "vector", k=5, scope={"d2"}, question="educación", embed=_embed)
    assert {h["doc_id"] for h in hits} == {"d2"}


def test_hybrid_fuses_both(tmp_path):
    conn = _seed(tmp_path)
    hits = retrieve.retrieve(conn, "hybrid", k=3, scope=None, question="educación", embed=_embed)
    refs = [h["ref"] for h in hits]
    assert set(refs) == {"r1", "r2", "r3"}  # vector + lexical union, rrf-ranked
    assert all(h["retriever"] in ("vector", "lexical", "both") for h in hits)


def test_none_mode_returns_empty(tmp_path):
    conn = _seed(tmp_path)
    assert retrieve.retrieve(conn, "none", k=5, scope=None, question="x", embed=_embed) == []


def test_empty_scope_returns_empty(tmp_path):
    conn = _seed(tmp_path)
    assert retrieve.retrieve(conn, "vector", k=5, scope=set(), question="x", embed=_embed) == []


def test_lexical_handles_spanish_punctuation(tmp_path):
    conn = _seed(tmp_path)
    hits = retrieve.retrieve(conn, "lexical", k=5, scope=None, question="¿política?", embed=_embed)
    assert [h["ref"] for h in hits] == ["r2"]


def test_lexical_empty_after_sanitize_returns_empty(tmp_path):
    conn = _seed(tmp_path)
    assert retrieve.retrieve(conn, "lexical", k=5, scope=None, question="¿?", embed=_embed) == []


def test_hybrid_survives_all_punctuation_question(tmp_path):
    conn = _seed(tmp_path)
    # lexical yields nothing after sanitize; vector still returns hits — must not crash
    hits = retrieve.retrieve(conn, "hybrid", k=3, scope=None, question="¿?", embed=_embed)
    assert hits and all(h["retriever"] == "vector" for h in hits)


def test_retrieve_many_single_query_equals_retrieve(tmp_path):
    conn = _seed(tmp_path)
    one = retrieve.retrieve(conn, "lexical", k=5, scope=None, question="política", embed=_embed)
    many = retrieve.retrieve_many(conn, "lexical", k=5, scope=None, queries=["política"], embed=_embed)
    assert [h["ref"] for h in many] == [h["ref"] for h in one]


def test_retrieve_many_fuses_multiple_queries(tmp_path):
    conn = _seed(tmp_path)
    # "educación" (lexical) hits r1 & r3; "política" hits r2. Neither single query
    # returns all three; the fused multi-query result must.
    many = retrieve.retrieve_many(conn, "lexical", k=5, scope=None,
                                  queries=["educación", "política"], embed=_embed)
    assert {h["ref"] for h in many} == {"r1", "r2", "r3"}


def test_retrieve_many_respects_k_after_fusion(tmp_path):
    conn = _seed(tmp_path)
    many = retrieve.retrieve_many(conn, "lexical", k=1, scope=None,
                                  queries=["educación", "política"], embed=_embed)
    assert len(many) == 1
