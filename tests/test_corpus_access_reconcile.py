import json
import textwrap
from pathlib import Path

import yaml

from shapes.corpus.access import reconcile, index
from shapes.corpus.engine import sidecar


def _machine(tmp_path, dim=4):
    binp = tmp_path / "fake_embed.py"
    binp.write_text(textwrap.dedent(f"""
        import sys, json
        for l in sys.stdin:
            l = l.strip()
            if l:
                c = json.loads(l)
                print(json.dumps({{"ref": c["ref"], "vector": [0.1]*{dim},
                                   "dim": {dim}, "model": "fake"}}))
    """).strip())
    table = {"capabilities": {"local.embed": {
        "run": ["python3", str(binp)], "reads": "stdin", "emits": "stdout"}}}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return tmp_path


def _corpus(tmp_path):
    corpus = tmp_path / "content" / "c"; corpus.mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\nask: ./ask.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\n"
        "fields: {tipo: {type: enum, values: [a, b], by: model}}\n"
        "pipeline: [{id: stamp, uses: engine.stamp}]\n")
    return corpus


def _bundle(corpus, doc_id, tipo, chunks):
    pair = corpus / "corpus" / doc_id; pair.mkdir(parents=True)
    (pair / "chunks.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in chunks))
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "complete",
        "stages": [{"id": "characterize", "fields": {"tipo": tipo}}],
        "artifacts": {}})
    return pair


def test_index_embeds_new_and_caches_projection(tmp_path):
    machine = _machine(tmp_path); corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a",
            [{"ref": "r1", "span": [0, 5], "text": "hola"},
             {"ref": "r2", "span": [5, 9], "text": "mundo"}])
    summary = reconcile.reconcile(corpus, machine)
    assert summary["embedded"] == 1 and summary["total"] == 1
    conn = index.open_index(corpus)
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 2
    folded = conn.execute(
        "SELECT folded FROM projection WHERE doc_id='aaaaaaaaaaaa'").fetchone()[0]
    assert json.loads(folded)["tipo"] == "a"


def test_index_is_idempotent(tmp_path):
    machine = _machine(tmp_path); corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    reconcile.reconcile(corpus, machine)
    again = reconcile.reconcile(corpus, machine)
    assert again["embedded"] == 0 and again["dropped"] == 0 and again["refreshed"] == 0


def test_retired_doc_is_dropped(tmp_path):
    machine = _machine(tmp_path); corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    reconcile.reconcile(corpus, machine)
    # retire it: move the bundle out of corpus/
    (corpus / "corpus" / "aaaaaaaaaaaa").rename(corpus / "retired_tmp")
    (corpus / "retired").mkdir()
    (corpus / "retired_tmp").rename(corpus / "retired" / "aaaaaaaaaaaa")
    summary = reconcile.reconcile(corpus, machine)
    assert summary["dropped"] == 1
    conn = index.open_index(corpus)
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0


def _machine_marked(tmp_path, dim=4):
    """Embedder that logs each invocation, so tests can assert it was NOT run."""
    calls = tmp_path / "embed_calls.log"
    binp = tmp_path / "fake_embed.py"
    binp.write_text(textwrap.dedent(f"""
        import sys, json, pathlib
        with open({str(calls)!r}, "a") as f:
            f.write("call\\n")
        for l in sys.stdin:
            l = l.strip()
            if l:
                c = json.loads(l)
                print(json.dumps({{"ref": c["ref"], "vector": [0.1]*{dim},
                                   "dim": {dim}, "model": "fake"}}))
    """).strip())
    table = {"capabilities": {"local.embed": {
        "run": ["python3", str(binp)], "reads": "stdin", "emits": "stdout"}}}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return tmp_path, calls


def _embedded_corpus(tmp_path):
    corpus = _corpus(tmp_path)
    (corpus / "ask.yaml").write_text("index:\n  uses: local.embed\n")
    return corpus


def _calls(calls_log) -> int:
    return len(calls_log.read_text().splitlines()) if calls_log.exists() else 0


def test_reconcile_vectors_false_indexes_text_without_bulk_embedding(tmp_path):
    machine, calls = _machine_marked(tmp_path)
    corpus = _embedded_corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a",
            [{"ref": "r1", "span": [0, 5], "text": "hola"},
             {"ref": "r2", "span": [5, 9], "text": "mundo"}])
    summary = reconcile.reconcile(corpus, machine, vectors=False)
    assert summary["embedded"] == 1 and summary["pending"] == 1
    conn = index.open_index(corpus)
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM fts_chunks").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM vec_chunks").fetchone()[0] == 0
    assert _calls(calls) <= 1          # at most the identity probe — never per-doc
    conn.close()
    n = _calls(calls)
    reconcile.reconcile(corpus, machine, vectors=False)   # warm: index exists
    assert _calls(calls) == n          # no probe, no embeds — embedder untouched


def test_vector_retrieve_refuses_while_vectors_pending(tmp_path):
    import pytest
    from shapes.corpus.access import retrieve
    machine, _ = _machine_marked(tmp_path)
    corpus = _embedded_corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a", [{"ref": "r1", "span": [0, 5], "text": "hola"}])
    reconcile.reconcile(corpus, machine, vectors=False)
    conn = index.open_index(corpus)
    for mode in ("vector", "hybrid"):
        with pytest.raises(ValueError, match="pending"):
            retrieve.retrieve(conn, mode, 5, None, "hola", lambda q: [0.1] * 4)


def test_full_reconcile_completes_pending_vectors(tmp_path):
    machine, calls = _machine_marked(tmp_path)
    corpus = _embedded_corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a",
            [{"ref": "r1", "span": [0, 5], "text": "hola"},
             {"ref": "r2", "span": [5, 9], "text": "mundo"}])
    reconcile.reconcile(corpus, machine, vectors=False)
    summary = reconcile.reconcile(corpus, machine)
    assert summary["vectored"] == 1 and summary["pending"] == 0
    conn = index.open_index(corpus)
    assert conn.execute("SELECT count(*) FROM vec_chunks").fetchone()[0] == 2
    again = reconcile.reconcile(corpus, machine)          # idempotent
    assert again["vectored"] == 0 and again["embedded"] == 0


def test_index_uses_wal_and_busy_timeout(tmp_path):
    """Readers (the catalogue search) must not block behind a long vector
    write — WAL isolates them; the busy timeout absorbs writer/writer overlap."""
    machine, _ = _machine_marked(tmp_path)
    corpus = _embedded_corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a", [{"ref": "r1", "span": [0, 5], "text": "hola"}])
    reconcile.reconcile(corpus, machine, vectors=False)
    conn = index.open_index(corpus)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 30000


def test_embed_pending_commits_per_doc(tmp_path):
    """A vector backfill that dies mid-run must keep the docs it finished —
    the write lock is held per doc, never across the whole batch."""
    import textwrap as tw
    calls = tmp_path / "embed_calls.log"
    binp = tmp_path / "fake_embed.py"
    binp.write_text(tw.dedent(f"""
        import sys, json, pathlib
        log = pathlib.Path({str(calls)!r})
        n = len(log.read_text().splitlines()) if log.exists() else 0
        log.open("a").write("call\\n")
        if n >= 2:                      # probe + first doc succeed; second doc dies
            sys.exit(1)
        for l in sys.stdin:
            l = l.strip()
            if l:
                c = json.loads(l)
                print(json.dumps({{"ref": c["ref"], "vector": [0.1]*4,
                                   "dim": 4, "model": "fake"}}))
    """).strip())
    table = {"capabilities": {"local.embed": {
        "run": ["python3", str(binp)], "reads": "stdin", "emits": "stdout"}}}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    corpus = _embedded_corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a", [{"ref": "r1", "span": [0, 5], "text": "hola"}])
    _bundle(corpus, "bbbbbbbbbbbb", "b", [{"ref": "r2", "span": [0, 5], "text": "mundo"}])
    import pytest
    with pytest.raises(Exception):
        reconcile.reconcile(corpus, machine_root=tmp_path)
    conn = index.open_index(corpus)
    assert conn.execute("SELECT count(*) FROM vec_chunks").fetchone()[0] == 1  # first doc kept


def test_open_index_never_mutates_journal_mode(tmp_path):
    """Readers must not write: opening an existing rollback-journal index must
    leave it rollback (prod ships rollback onto a read-only mount)."""
    machine, _ = _machine_marked(tmp_path)
    corpus = _embedded_corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a", [{"ref": "r1", "span": [0, 5], "text": "hola"}])
    reconcile.reconcile(corpus, machine, vectors=False)
    conn = index.open_index(corpus)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    conn = index.open_index(corpus)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_open_index_reads_on_readonly_media(tmp_path):
    """The box mounts the corpus volume :ro — open + SELECT must work there.
    This is the ask-502 prod regression of 2026-08-31."""
    import os, stat
    machine, _ = _machine_marked(tmp_path)
    corpus = _embedded_corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a", [{"ref": "r1", "span": [0, 5], "text": "hola"}])
    reconcile.reconcile(corpus, machine)                  # full build, then freeze
    conn = index.open_index(corpus)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode=DELETE")            # ship-mode artifact
    conn.close()
    idx = corpus / "index"
    for p in idx.iterdir():
        p.chmod(0o444)
    idx.chmod(0o555)
    try:
        conn = index.open_index(corpus)
        n = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        assert n == 1
        conn.close()
    finally:
        idx.chmod(0o755)
        for p in idx.iterdir():
            p.chmod(0o644)


def test_embed_pending_survives_concurrent_backfill(tmp_path, monkeypatch):
    """Two reconciles race: another writer lands the same doc's vectors between
    this one's pending scan and its inserts. The insert must tolerate it, not
    crash the ask with a UNIQUE constraint error."""
    machine = _machine(tmp_path); corpus = _corpus(tmp_path)
    (corpus / "ask.yaml").write_text("index:\n  uses: local.embed\n")
    _bundle(corpus, "aaaaaaaaaaaa", "a",
            [{"ref": "r1", "span": [0, 4], "text": "hola"},
             {"ref": "r2", "span": [4, 9], "text": "mundo"}])
    reconcile.reconcile(corpus, machine, vectors=False)   # text landed, vectors pending

    from shapes.corpus.access import passport
    real_embed = passport.embed

    def racing_embed(chunks, machine_root):
        vectors = real_embed(chunks, machine_root)
        other = index.open_index(corpus)              # the concurrent writer wins
        for v in vectors:
            row = other.execute("SELECT rowid FROM chunks WHERE ref=?",
                                (v["ref"],)).fetchone()
            if row is None:                           # the passport probe, not a chunk
                continue
            other.execute("INSERT INTO vec_chunks(rowid, doc_id, embedding) VALUES (?,?,?)",
                          (row[0], "aaaaaaaaaaaa", index.serialize(v["vector"])))
        other.commit(); other.close()
        return vectors

    monkeypatch.setattr(reconcile.passport, "embed", racing_embed)
    reconcile.reconcile(corpus, machine)              # must not raise
    conn = index.open_index(corpus)
    assert conn.execute("SELECT count(*) FROM chunks WHERE rowid NOT IN "
                        "(SELECT rowid FROM vec_chunks)").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM vec_chunks").fetchone()[0] == 2


def test_embed_pending_tolerates_duplicate_refs_within_a_doc(tmp_path):
    # A ref is a content hash: two identical passages in one doc share one ref.
    # Vectors come back in chunk order (passport.embed guarantees it), so the
    # backfill must map by position — keying by ref inserted the same rowid twice
    # (UNIQUE constraint on vec_chunks) and every ask died in reconcile.
    machine, _ = _machine_marked(tmp_path)
    corpus = _embedded_corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", "a",
            [{"ref": "same", "span": [0, 5], "text": "hola"},
             {"ref": "same", "span": [5, 10], "text": "hola"},
             {"ref": "r2", "span": [10, 15], "text": "mundo"}])
    reconcile.reconcile(corpus, machine, vectors=False)
    summary = reconcile.reconcile(corpus, machine)
    assert summary["vectored"] == 1 and summary["pending"] == 0
    conn = index.open_index(corpus)
    assert conn.execute("SELECT count(*) FROM vec_chunks").fetchone()[0] == 3
