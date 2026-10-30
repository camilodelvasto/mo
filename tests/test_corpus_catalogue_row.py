# tests/test_corpus_catalogue_row.py
from fastapi.testclient import TestClient

from shapes.corpus.service.app import create_app
from shapes.corpus.service.cache import Cache
from tests.test_corpus_cache import FLOW, _corpus, _pair


def test_cache_row_returns_one_row(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa",
          [{"id": "classify", "fields": {"doc_type": "interview"}}], "complete")
    cache = Cache(corpus, FLOW)
    cache.reconcile()
    row = cache.row("aaaaaaaaaaaa")
    assert row["doc_id"] == "aaaaaaaaaaaa" and row["status"] == "complete"
    assert cache.row("ffffffffffff") is None


def test_catalogue_row_endpoint(tmp_path):
    from tests.test_corpus_service_reads import _corpus as svc_corpus, _pair as svc_pair
    corpus = svc_corpus(tmp_path)
    svc_pair(corpus, "corpus", "aaaaaaaaaaaa",
             [{"id": "classify", "fields": {"doc_type": "interview"}}], "complete")
    client = TestClient(create_app(corpus))
    r = client.get("/catalogue/aaaaaaaaaaaa")
    assert r.status_code == 200 and r.json()["doc_id"] == "aaaaaaaaaaaa"
    assert client.get("/catalogue/ffffffffffff").status_code == 404
    assert client.get("/catalogue/counts").status_code == 200
