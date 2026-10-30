# tests/test_corpus_tui_sse.py
import asyncio

import pytest
import yaml

from shapes.corpus.engine import sidecar
from shapes.corpus.renderer.tui.client import embed_client

FLOW = {"id": "t", "version": 1, "fields": {},
        "entrypoints": [{"id": "g", "area": "dropbox/general"}],
        "pipeline": [{"id": "stamp", "uses": "engine.stamp"}]}


def _corpus(tmp_path):
    corpus = tmp_path / "c"
    (corpus / "derived").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(yaml.safe_dump(FLOW))
    return corpus


@pytest.mark.skip(reason="SSE-over-ASGITransport unreliable in-process; SseTrigger is for the remote transport over a real socket")
@pytest.mark.asyncio
async def test_sse_over_asgitransport_delivers_a_change(tmp_path):
    """The spike: does an /events SSE stream deliver an in-process change to the
    client over ASGITransport?"""
    corpus = _corpus(tmp_path)
    client, app = embed_client(corpus)
    received = []

    async def consume():
        async for change in client.events():
            received.append(change)
            return

    try:
        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        pair = corpus / "corpus" / "aaaaaaaaaaaa"
        pair.mkdir(parents=True)
        sidecar.write(pair / "meta.yaml", {
            "doc_id": "aaaaaaaaaaaa", "flow": {"id": "t", "version": 1,
            "hash": "sha256:0"}, "status": "complete", "stages": [], "artifacts": {}})
        app.state.poll_once()
        await asyncio.wait_for(task, timeout=2.0)
        assert received and received[0]["doc_id"] == "aaaaaaaaaaaa"
    finally:
        await client.aclose()
