# tests/test_corpus_service_writes.py
from fastapi.testclient import TestClient

from shapes.corpus.service.app import create_app
from tests.test_corpus_service_reads import _corpus, _pair


def _client(corpus):
    (corpus / "inbox").mkdir(exist_ok=True)
    return TestClient(create_app(corpus))


def test_post_assert_writes_one_inbox_file(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa", [], "complete")
    client = _client(corpus)
    r = client.post("/assert", json={"doc_id": "aaaaaaaaaaaa",
                                     "fields": {"consent": "given"}})
    assert r.status_code == 200
    name = r.json()["inbox"]
    assert name.endswith("-aaaaaaaaaaaa.assert.yaml")
    files = list((corpus / "inbox").glob("*.assert.yaml"))
    assert len(files) == 1 and files[0].name == name


def test_post_assert_surfaces_as_pending(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa", [], "complete")
    client = _client(corpus)
    client.post("/assert", json={"doc_id": "aaaaaaaaaaaa",
                                 "fields": {"consent": "given"}})
    client.app.state.cache.tick()       # cache re-reads inbox
    row = client.get("/catalogue").json()["rows"][0]
    assert row["pending"] == ["consent"]


def test_post_order_writes_one_inbox_file(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa", [], "complete")
    client = _client(corpus)
    r = client.post("/order", json={"doc_id": "aaaaaaaaaaaa", "action": "retire"})
    assert r.status_code == 200
    name = r.json()["inbox"]
    assert name.endswith("-aaaaaaaaaaaa.order.yaml")
    assert (corpus / "inbox" / name).is_file()
