# tests/test_corpus_tui_client_doc.py
import json

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


def _doc(corpus, doc_id="aaaaaaaaaaaa"):
    pair = corpus / "corpus" / doc_id
    pair.mkdir(parents=True)
    (pair / "transcript.md").write_text("# Über\n\nWohnung text.\n", encoding="utf-8")
    (pair / "chunks.jsonl").write_text(
        json.dumps({"ref": "c0a1b2c3d", "ast_path": "Über", "span": [0, 7],
                    "contiguous": True, "text": "# Über\n"}) + "\n")
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
        "status": "complete",
        "stages": [{"id": "received", "hash": "sha256:0", "fields": {}},
                   {"id": "classify", "fields": {"doc_type": "interview"}},
                   {"id": "chunk",
                    "input": {"artifact": "transcript", "hash": "sha256:bb"},
                    "output": {"artifact": "chunks", "hash": "sha256:cc"}, "fields": {}}],
        "artifacts": {"transcript": {"path": "./transcript.md"},
                      "chunks": {"path": "./chunks.jsonl"}}})
    return pair


@pytest.mark.asyncio
async def test_client_doc_custody_chunks_log(tmp_path):
    corpus = _corpus(tmp_path)
    _doc(corpus)
    client, _app = embed_client(corpus)
    try:
        doc = await client.doc("aaaaaaaaaaaa")
        assert doc["fields"]["doc_type"]["value"] == "interview"
        assert (await client.custody("aaaaaaaaaaaa"))["links"][0]["stage"] == "chunk"
        assert (await client.chunks("aaaaaaaaaaaa"))["chunks"][0]["ref"] == "c0a1b2c3d"
        assert len((await client.log("aaaaaaaaaaaa"))["entries"]) == 3
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_artifact_returns_raw_bytes(tmp_path):
    corpus = _corpus(tmp_path)
    _doc(corpus)
    client, _app = embed_client(corpus)
    try:
        raw = await client.artifact("aaaaaaaaaaaa", "transcript")
        assert isinstance(raw, bytes)
        assert raw.decode("utf-8") == "# Über\n\nWohnung text.\n"
    finally:
        await client.aclose()
