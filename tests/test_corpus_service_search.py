import json
import pytest
import httpx
from httpx import ASGITransport

from shapes.corpus.service.app import create_app
from shapes.corpus.engine import sidecar


def _corpus(tmp_path):
    corpus = tmp_path / "content" / "c"; corpus.mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\n"
        "fields: {tipo: {type: enum, values: [a, b], by: model}}\n"
        "pipeline: [{id: stamp, uses: engine.stamp}]\n")
    pair = corpus / "corpus" / "aaaaaaaaaaaa"; pair.mkdir(parents=True)
    (pair / "chunks.jsonl").write_text(
        json.dumps({"ref": "r1", "span": [0, 20], "text": "voté por Petro"}) + "\n")
    sidecar.write(pair / "meta.yaml", {
        "doc_id": "aaaaaaaaaaaa", "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "complete",
        "stages": [{"id": "characterize", "fields": {"tipo": "a"}}], "artifacts": {}})
    return corpus


@pytest.mark.asyncio
async def test_search_endpoint_returns_content_hits(tmp_path):
    corpus = _corpus(tmp_path)
    app = create_app(corpus, machine_root=tmp_path)
    async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                 base_url="http://embed") as http:
        r = await http.get("/search", params={"q": "petro"})
        assert r.status_code == 200
        hits = r.json()["hits"]
        assert [h["doc_id"] for h in hits] == ["aaaaaaaaaaaa"]
        assert "Petro" in hits[0]["snippet"]
        empty = await http.get("/search", params={"q": ""})
        assert empty.json()["hits"] == []
