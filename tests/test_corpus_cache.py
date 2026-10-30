# tests/test_corpus_cache.py
from pathlib import Path

from shapes.corpus.engine import sidecar
from shapes.corpus.service.cache import Cache

FLOW = {"id": "t", "version": 1,
        "fields": {"visibility": {"type": "string", "by": "operator"},
                   "doc_type": {"type": "enum", "values": ["interview"],
                                "by": "model"},
                   "project": {"type": "string", "by": "operator"}},
        "entrypoints": [{"id": "g", "area": "dropbox/general"}],
        "pipeline": [{"id": "stamp", "uses": "engine.stamp"}]}


def _corpus(tmp_path):
    corpus = tmp_path / "c"
    (corpus / "derived").mkdir(parents=True)
    return corpus


def _pair(corpus, area, doc_id, stages, status):
    pair = corpus / area / doc_id
    pair.mkdir(parents=True)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
        "status": status, "stages": stages, "artifacts": {}})
    return pair


def test_reconcile_folds_the_tree_and_counts_lenses(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "working/datasheet", "aaaaaaaaaaaa",
          [{"id": "datasheet", "fields": {}, "parked": ["consent"]}],
          "parked@datasheet")
    _pair(corpus, "corpus", "bbbbbbbbbbbb",
          [{"id": "classify", "fields": {"doc_type": "interview"}}], "complete")
    _pair(corpus, "retired", "cccccccccccc", [{"id": "retired", "fields": {}}],
          "retired")
    cache = Cache(corpus, FLOW)
    cache.reconcile()
    counts = cache.lens_counts()
    assert counts["all"] == 3
    assert counts["hard"] == 1
    assert counts["soft"] == 1
    assert counts["retired"] == 1
    rows = cache.catalogue(lens="all")["rows"]
    assert {r["doc_id"] for r in rows} == {"aaaaaaaaaaaa", "bbbbbbbbbbbb",
                                           "cccccccccccc"}


def test_where_filter_on_status_and_field(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "bbbbbbbbbbbb",
          [{"id": "classify", "fields": {"doc_type": "interview"}}], "complete")
    _pair(corpus, "corpus", "dddddddddddd",
          [{"id": "classify", "fields": {"doc_type": "workshop"}}], "complete")
    cache = Cache(corpus, FLOW)
    cache.reconcile()
    rows = cache.catalogue(where={"doc_type": "interview"})["rows"]
    assert [r["doc_id"] for r in rows] == ["bbbbbbbbbbbb"]


def test_tick_detects_a_move_and_emits_change(tmp_path):
    corpus = _corpus(tmp_path)
    pair = _pair(corpus, "working/stamp", "aaaaaaaaaaaa", [], "in-flight@stamp")
    cache = Cache(corpus, FLOW)
    cache.reconcile()
    dest = corpus / "corpus" / "aaaaaaaaaaaa"
    dest.parent.mkdir(parents=True)
    pair.rename(dest)
    doc = sidecar.read(dest / "meta.yaml")
    doc["status"] = "complete"
    sidecar.write(dest / "meta.yaml", doc)
    changed = cache.tick()
    assert "aaaaaaaaaaaa" in {c["doc_id"] for c in changed}
    row = cache.catalogue(where={})["rows"][0]
    assert row["status"] == "complete"


def test_tick_skips_torn_sidecar_then_heals(tmp_path):
    corpus = _corpus(tmp_path)
    cache = Cache(corpus, FLOW)
    cache.reconcile()
    torn = corpus / "corpus" / "aaaaaaaaaaaa"
    torn.mkdir(parents=True)
    (torn / "meta.yaml").write_text("doc_id: [unclosed")
    assert cache.tick() == []
    sidecar.write(torn / "meta.yaml", {
        "doc_id": "aaaaaaaaaaaa", "flow": {"id": "t", "version": 1,
        "hash": "sha256:0"}, "status": "complete", "stages": [], "artifacts": {}})
    changed = cache.tick()
    assert "aaaaaaaaaaaa" in {c["doc_id"] for c in changed}


def test_rebuild_drops_and_refolds(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "bbbbbbbbbbbb", [], "complete")
    cache = Cache(corpus, FLOW)
    cache.reconcile()
    import shutil
    shutil.rmtree(corpus / "corpus" / "bbbbbbbbbbbb")
    cache.rebuild()
    assert cache.lens_counts()["all"] == 0
