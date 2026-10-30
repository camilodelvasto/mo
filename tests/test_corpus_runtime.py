# tests/test_corpus_runtime.py
import os
import stat

from shapes.corpus.service import runtime
from shapes.corpus.service.cache import Cache
from shapes.corpus.engine import sidecar

FLOW = {"id": "t", "version": 1,
        "fields": {"doc_type": {"type": "enum", "values": ["interview"], "by": "model"}},
        "entrypoints": [{"id": "g", "area": "dropbox"}],
        "pipeline": [{"id": "stamp", "uses": "engine.stamp"}]}


def _pair(corpus, area, doc_id, stages, status):
    pair = corpus / area / doc_id
    pair.mkdir(parents=True)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
        "status": status, "stages": stages, "artifacts": {}})


def test_corpus_path_lives_outside_the_corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUI_RUNTIME_DIR", str(tmp_path / "rt"))
    corpus = tmp_path / "c"; corpus.mkdir()
    p = runtime.corpus_path(corpus, "catalogue.sqlite")
    assert corpus.resolve() not in p.resolve().parents        # NOT inside the corpus
    assert (tmp_path / "rt").resolve() in p.resolve().parents  # in the runtime dir


def test_corpus_path_keyed_by_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUI_RUNTIME_DIR", str(tmp_path / "rt"))
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    assert runtime.corpus_path(a, "x") == runtime.corpus_path(a, "x")   # same corpus → same
    assert runtime.corpus_path(a, "x") != runtime.corpus_path(b, "x")   # different → different


def test_cache_db_is_not_written_into_the_corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUI_RUNTIME_DIR", str(tmp_path / "rt"))
    corpus = tmp_path / "c"; corpus.mkdir()
    _pair(corpus, "corpus", "bbbbbbbbbbbb",
          [{"id": "classify", "fields": {"doc_type": "interview"}}], "complete")
    cache = Cache(corpus, FLOW)
    cache.reconcile()
    assert not (corpus / "derived").exists()                      # corpus untouched
    assert runtime.corpus_path(corpus, "catalogue.sqlite").exists()  # db in runtime dir
    assert cache.lens_counts()["all"] == 1


def test_cache_builds_against_a_readonly_corpus(tmp_path, monkeypatch):
    # the serve cannot mutate the data it serves — a read-only corpus mount is
    # the enforcement. The cache must still build, writing only to the runtime dir.
    monkeypatch.setenv("MOUI_RUNTIME_DIR", str(tmp_path / "rt"))
    corpus = tmp_path / "c"; corpus.mkdir()
    _pair(corpus, "corpus", "bbbbbbbbbbbb",
          [{"id": "classify", "fields": {"doc_type": "interview"}}], "complete")
    _pair(corpus, "working/datasheet", "aaaaaaaaaaaa",
          [{"id": "datasheet", "fields": {}, "parked": ["consent"]}], "parked@datasheet")

    # make the whole corpus tree read-only (dirs + files)
    paths = [corpus] + [p for p in corpus.rglob("*")]
    for p in paths:
        p.chmod(p.stat().st_mode & ~0o222)
    try:
        cache = Cache(corpus, FLOW)        # would raise "readonly database" if the db were inside
        cache.reconcile()
        assert cache.lens_counts()["all"] == 2
    finally:
        for p in paths:                    # restore so tmp cleanup can remove the tree
            p.chmod(p.stat().st_mode | stat.S_IWUSR)
