import json
from pathlib import Path

from shapes.corpus.access import search
from shapes.corpus.engine import sidecar


def _corpus(tmp_path):
    corpus = tmp_path / "content" / "c"; corpus.mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\n"
        "fields: {tipo: {type: enum, values: [a, b], by: model}}\n"
        "pipeline: [{id: stamp, uses: engine.stamp}]\n")
    return corpus


def _bundle(corpus, doc_id, chunks):
    pair = corpus / "corpus" / doc_id; pair.mkdir(parents=True)
    (pair / "chunks.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in chunks))
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "complete",
        "stages": [{"id": "characterize", "fields": {"tipo": "a"}}],
        "artifacts": {}})
    return pair


def test_rolls_chunk_hits_up_to_distinct_docs(tmp_path):
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa",
            [{"ref": "r1", "span": [0, 20], "text": "voté por Petro en marzo"},
             {"ref": "r2", "span": [20, 40], "text": "Petro y la campaña"}])
    _bundle(corpus, "bbbbbbbbbbbb",
            [{"ref": "r3", "span": [0, 10], "text": "sin el término"}])
    hits = search.search_docs(corpus, tmp_path, "petro")
    assert [h["doc_id"] for h in hits] == ["aaaaaaaaaaaa"]   # one doc, deduped
    assert "Petro" in hits[0]["snippet"]


def test_finds_a_freshly_added_doc(tmp_path):
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 5], "text": "hola"}])
    assert search.search_docs(corpus, tmp_path, "petro") == []   # not present yet
    _bundle(corpus, "cccccccccccc",
            [{"ref": "r9", "span": [0, 20], "text": "entrevista sobre Petro"}])
    hits = search.search_docs(corpus, tmp_path, "petro")          # reconcile-before-search
    assert [h["doc_id"] for h in hits] == ["cccccccccccc"]


def test_empty_query_returns_empty(tmp_path):
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 5], "text": "petro"}])
    assert search.search_docs(corpus, tmp_path, "   ") == []


def test_search_never_bulk_embeds_on_an_embedded_corpus(tmp_path):
    """The catalogue search is lexical; it must not pay the vector-embedding
    cost for freshly ingested docs (45 pending docs froze the TUI for minutes)."""
    import textwrap
    import yaml
    corpus = _corpus(tmp_path)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\nask: ./ask.yaml\n")
    (corpus / "ask.yaml").write_text("index:\n  uses: local.embed\n")
    calls = tmp_path / "embed_calls.log"
    binp = tmp_path / "fake_embed.py"
    binp.write_text(textwrap.dedent(f"""
        import sys, json
        with open({str(calls)!r}, "a") as f:
            f.write("call\\n")
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
    _bundle(corpus, "aaaaaaaaaaaa",
            [{"ref": "r1", "span": [0, 20], "text": "entrevista sobre Petro"}])
    _bundle(corpus, "bbbbbbbbbbbb",
            [{"ref": "r2", "span": [0, 10], "text": "otra cosa"}])
    hits = search.search_docs(corpus, tmp_path, "petro")
    assert [h["doc_id"] for h in hits] == ["aaaaaaaaaaaa"]
    n = len(calls.read_text().splitlines()) if calls.exists() else 0
    assert n <= 1                       # at most the identity probe, never per-doc
    search.search_docs(corpus, tmp_path, "petro")         # warm: index exists
    n2 = len(calls.read_text().splitlines()) if calls.exists() else 0
    assert n2 == n                      # a warm search never touches the embedder
