from shapes.corpus.access import index, stitch


def _seed(tmp_path):
    """Two docs. d1 has five chunks in span order; rowids are deliberately
    shuffled so adjacency must come from (doc_id, span), never rowid. d2 has
    one chunk sitting between d1's rowids to catch cross-doc leaks."""
    corpus = tmp_path / "c"; corpus.mkdir()
    conn = index.open_index(corpus, dim=3)
    rows = [
        (7, "d1", "a", 0, 2, "A."),
        (3, "d1", "b", 4, 6, "B."),
        (9, "d1", "c", 8, 10, "C."),
        (1, "d1", "d", 12, 14, "D."),
        (5, "d1", "e", 16, 18, "E."),
        (4, "d2", "x", 0, 2, "X."),
    ]
    for rowid, doc, ref, start, end, text in rows:
        conn.execute("INSERT INTO chunks(rowid, doc_id, ref, span_start, span_end, text) "
                     "VALUES (?,?,?,?,?,?)", (rowid, doc, ref, start, end, text))
    conn.commit()
    return conn


def _hit(doc_id, ref, span, text, score, retriever="both"):
    return {"doc_id": doc_id, "ref": ref, "span": span, "text": text,
            "score": score, "retriever": retriever}


def test_radius_zero_is_identity(tmp_path):
    conn = _seed(tmp_path)
    hits = [_hit("d1", "c", [8, 10], "C.", 0.5)]
    assert stitch.stitch(conn, hits, 0) == hits


def test_hit_pulls_one_neighbor_each_side(tmp_path):
    conn = _seed(tmp_path)
    out = stitch.stitch(conn, [_hit("d1", "c", [8, 10], "C.", 0.5)], 1)
    assert len(out) == 1
    p = out[0]
    assert p["text"] == "B.\n\nC.\n\nD."
    assert p["span"] == [4, 14]
    assert p["refs"] == ["b", "c", "d"]
    assert p["ref"] == "c"                 # the hit stays the citable anchor
    assert p["score"] == 0.5
    assert p["retriever"] == "both"


def test_stops_at_doc_boundaries(tmp_path):
    conn = _seed(tmp_path)
    out = stitch.stitch(conn, [_hit("d1", "a", [0, 2], "A.", 0.5)], 1)
    assert out[0]["text"] == "A.\n\nB."
    assert out[0]["refs"] == ["a", "b"]


def test_adjacent_hits_merge_into_one_passage(tmp_path):
    conn = _seed(tmp_path)
    hits = [_hit("d1", "b", [4, 6], "B.", 0.9),
            _hit("d1", "d", [12, 14], "D.", 0.4)]
    out = stitch.stitch(conn, hits, 1)      # neighbors a,c and c,e — one run a..e
    assert len(out) == 1
    p = out[0]
    assert p["text"] == "A.\n\nB.\n\nC.\n\nD.\n\nE."
    assert p["refs"] == ["a", "b", "c", "d", "e"]
    assert p["ref"] == "b"                  # highest-ranked member hit anchors
    assert p["score"] == 0.9


def test_input_ranking_is_preserved(tmp_path):
    conn = _seed(tmp_path)
    # input is ranked best-first (retrieve's contract); scores are not
    # comparable across modes, so stitch must keep rank, never re-sort
    hits = [_hit("d1", "c", [8, 10], "C.", 0.8),
            _hit("d2", "x", [0, 2], "X.", 0.3)]
    out = stitch.stitch(conn, hits, 1)
    assert [p["doc_id"] for p in out] == ["d1", "d2"]
    assert out[1]["text"] == "X."                        # no cross-doc neighbors
    assert out[1]["refs"] == ["x"]


def test_neighbor_never_crosses_into_other_doc(tmp_path):
    conn = _seed(tmp_path)
    out = stitch.stitch(conn, [_hit("d2", "x", [0, 2], "X.", 0.5)], 2)
    assert out[0]["refs"] == ["x"]


def test_radius_two_reaches_further(tmp_path):
    conn = _seed(tmp_path)
    out = stitch.stitch(conn, [_hit("d1", "e", [16, 18], "E.", 0.5)], 2)
    assert out[0]["refs"] == ["c", "d", "e"]
    assert out[0]["text"] == "C.\n\nD.\n\nE."
