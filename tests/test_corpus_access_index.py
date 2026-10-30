from pathlib import Path

from shapes.corpus.access import index


def test_open_creates_schema_with_dim(tmp_path):
    corpus = tmp_path / "c"; corpus.mkdir()
    conn = index.open_index(corpus, dim=4)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert {"docs", "chunks", "projection"} <= tables
    # vec + fts virtual tables exist and accept a row
    conn.execute("INSERT INTO chunks(rowid, doc_id, ref, span_start, span_end, text) "
                 "VALUES (1,'aaaaaaaaaaaa','r1',0,5,'hello')")
    conn.execute("INSERT INTO vec_chunks(rowid, doc_id, embedding) VALUES (1,'aaaaaaaaaaaa',?)",
                 [index.serialize([0.1, 0.2, 0.3, 0.4])])
    conn.execute("INSERT INTO fts_chunks(rowid, text) VALUES (1,'hello')")
    conn.commit()
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 1


def test_reopen_without_dim_uses_existing_schema(tmp_path):
    corpus = tmp_path / "c"; corpus.mkdir()
    index.open_index(corpus, dim=4).close()
    conn = index.open_index(corpus)  # no dim — must not recreate, must open
    assert (corpus / "index" / "corpus.db").is_file()
    conn.close()
