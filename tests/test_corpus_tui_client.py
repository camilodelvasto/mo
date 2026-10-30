# tests/test_corpus_tui_client.py
import pytest
import yaml

from shapes.corpus.engine import sidecar
from shapes.corpus.renderer.tui.client import embed_client

FLOW = {"id": "t", "version": 1,
        "fields": {"doc_type": {"type": "enum", "values": ["interview"], "by": "model"}},
        "entrypoints": [{"id": "g", "area": "dropbox/general"}],
        "pipeline": [{"id": "stamp", "uses": "engine.stamp"}]}


def _corpus(tmp_path):
    corpus = tmp_path / "c"
    (corpus / "derived").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(yaml.safe_dump(FLOW))
    return corpus


def _pair(corpus, doc_id, status="complete"):
    pair = corpus / "corpus" / doc_id
    pair.mkdir(parents=True)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
        "status": status,
        "stages": [{"id": "classify", "fields": {"doc_type": "interview"}}],
        "artifacts": {}})


@pytest.mark.asyncio
async def test_embed_client_reads_status_catalogue_counts_row(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "aaaaaaaaaaaa")
    client, _app = embed_client(corpus)
    try:
        status = await client.status()
        assert status["counts"]["all"] == 1 and status["engine"] is False
        cat = await client.catalogue(lens="all")
        assert cat["rows"][0]["doc_id"] == "aaaaaaaaaaaa"
        assert (await client.counts())["all"] == 1
        assert (await client.row("aaaaaaaaaaaa"))["doc_id"] == "aaaaaaaaaaaa"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_embed_client_where_filter(tmp_path):
    corpus = _corpus(tmp_path)
    _pair(corpus, "aaaaaaaaaaaa")
    client, _app = embed_client(corpus)
    try:
        hit = await client.catalogue(where="doc_type=interview")
        assert len(hit["rows"]) == 1
        miss = await client.catalogue(where="doc_type=workshop")
        assert miss["rows"] == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_embed_client_fields_returns_all_declared(tmp_path):
    corpus = _corpus(tmp_path)
    client, _app = embed_client(corpus)
    try:
        resp = await client.fields()
        specs = resp["fields"]
        assert "doc_type" in specs
        assert specs["doc_type"]["type"] == "enum"
        assert specs["doc_type"]["values"] == ["interview"]
        assert specs["doc_type"]["by"] == "model"
    finally:
        await client.aclose()
