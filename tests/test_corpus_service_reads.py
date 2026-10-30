# tests/test_corpus_service_reads.py
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from shapes.corpus.engine import sidecar
from shapes.corpus.service.app import create_app

FLOW = {"id": "t", "version": 1,
        "fields": {"doc_type": {"type": "enum", "values": ["interview"],
                                "by": "model"},
                   "consent": {"type": "string", "by": "operator"}},
        "entrypoints": [{"id": "g", "area": "dropbox/general"}],
        "pipeline": [{"id": "stamp", "uses": "engine.stamp"}]}


def _corpus(tmp_path):
    corpus = tmp_path / "c"
    (corpus / "derived").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(yaml.safe_dump(FLOW))
    return corpus


def _pair(corpus, area, doc_id, stages, status, artifacts=None):
    pair = corpus / area / doc_id
    pair.mkdir(parents=True)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
        "status": status, "stages": stages, "artifacts": artifacts or {}})
    return pair


def _client(corpus):
    return TestClient(create_app(corpus))


def test_status_reports_area_counts(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa", [], "complete")
    r = _client(corpus).get("/status")
    assert r.status_code == 200
    assert r.json()["counts"]["all"] == 1


def test_catalogue_returns_rows_and_counts(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa",
          [{"id": "classify", "fields": {"doc_type": "interview"}}], "complete")
    client = _client(corpus)
    rows = client.get("/catalogue").json()["rows"]
    assert rows[0]["cells"]["doc_type"]["value"] == "interview"
    assert client.get("/catalogue/counts").json()["all"] == 1


def test_catalogue_bad_where_is_400(tmp_path):
    corpus = _corpus(tmp_path)
    r = _client(corpus).get("/catalogue", params={"where": "doc_type"})  # no =
    assert r.status_code == 400


def test_catalogue_where_filter(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa",
          [{"id": "classify", "fields": {"doc_type": "interview"}}], "complete")
    r = _client(corpus).get("/catalogue", params={"where": "doc_type=interview"})
    assert len(r.json()["rows"]) == 1
    r2 = _client(corpus).get("/catalogue", params={"where": "doc_type=workshop"})
    assert r2.json()["rows"] == []


def test_doc_live_folds_with_provenance(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa", [
        {"id": "classify", "capability": {"id": "local.llm"}, "locality": "local",
         "meters": {"confidence": 0.93}, "fields": {"doc_type": "interview"}},
        {"id": "assert", "by": "operator", "fields": {"consent": "given"}},
    ], "complete")
    body = _client(corpus).get("/doc/aaaaaaaaaaaa").json()
    assert body["fields"]["doc_type"]["provenance"]["stage"] == "classify"
    assert body["fields"]["consent"]["provenance"]["by"] == "operator"


def test_doc_unknown_is_404(tmp_path):
    corpus = _corpus(tmp_path)
    assert _client(corpus).get("/doc/ffffffffffff").status_code == 404


def test_chunks_and_custody_and_log(tmp_path):
    import json
    corpus = _corpus(tmp_path)
    pair = _pair(corpus, "corpus", "aaaaaaaaaaaa", [
        {"id": "received", "hash": "sha256:aa", "fields": {}},
        {"id": "chunk", "input": {"artifact": "transcript", "hash": "sha256:bb"},
         "output": {"artifact": "chunks", "hash": "sha256:cc"}, "fields": {}},
    ], "complete", artifacts={"chunks": {"path": "./chunks.jsonl"}})
    (pair / "chunks.jsonl").write_text(json.dumps(
        {"ref": "c043aa11", "ast_path": "a", "span": [0, 3], "contiguous": True,
         "text": "abc"}) + "\n")
    client = _client(corpus)
    assert client.get("/doc/aaaaaaaaaaaa/chunks").json()["chunks"][0]["ref"] == "c043aa11"
    assert client.get("/doc/aaaaaaaaaaaa/custody").json()["links"][0]["stage"] == "chunk"
    assert len(client.get("/doc/aaaaaaaaaaaa/log").json()["entries"]) == 2


def test_artifact_streams_bytes(tmp_path):
    corpus = _corpus(tmp_path)
    pair = _pair(corpus, "corpus", "aaaaaaaaaaaa", [], "complete",
                 artifacts={"transcript": {"path": "./transcript.md"}})
    (pair / "transcript.md").write_text("hello transcript")
    r = _client(corpus).get("/doc/aaaaaaaaaaaa/artifacts/transcript")
    assert r.status_code == 200 and r.content == b"hello transcript"


def test_doc_path_returns_the_absolute_artifact_path(tmp_path):
    corpus = _corpus(tmp_path)
    pair = _pair(corpus, "corpus", "aaaaaaaaaaaa", [], "complete",
                 artifacts={"transcript": {"path": "./transcript.md"}})
    (pair / "transcript.md").write_text("hi")
    r = _client(corpus).get("/doc/aaaaaaaaaaaa/path", params={"artifact": "transcript"})
    assert r.status_code == 200
    assert r.json()["path"] == str((pair / "transcript.md").resolve())


def test_doc_path_404_when_the_bytes_are_gone(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa", [], "complete",
          artifacts={"original": {"path": "./original.pdf"}})   # file never written
    r = _client(corpus).get("/doc/aaaaaaaaaaaa/path", params={"artifact": "original"})
    assert r.status_code == 404
