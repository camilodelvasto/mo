# tests/test_corpus_tui_span.py
import json

import pytest
import yaml
from rich.text import Text

from shapes.corpus.builtins import chunk_ast
from shapes.corpus.engine import sidecar
from shapes.corpus.renderer.tui import docrender
from shapes.corpus.renderer.tui.client import embed_client

# multi-byte UTF-8 (ä ö ü ß, and Über) BEFORE later spans — the offsets a German
# corpus actually exercises. An all-ASCII fixture would pass while C is broken.
TRANSCRIPT = (
    "# Über die Wohnung\n\n"
    "Die Wohnung ist schön, mit Ausblick über die Stadt.\n\n"
    "## Mietvertrag\n\n"
    "Befristet auf zwei Jahre, Kaution drei Kaltmieten.\n\n"
    "## Nebenkosten\n\n"
    "Heizung und Wasser zusammen achtzig Euro.\n"
)


def test_highlight_lights_the_span_region():
    markup = docrender.highlight("abcdefgh", [2, 5])
    plain = Text.from_markup(markup).plain
    assert plain == "abcdefgh"                 # all text present, colour-stripped
    assert "cde" in plain                      # the lit region is the span slice


def _corpus_with_real_chunks(tmp_path):
    corpus = tmp_path / "c"
    (corpus / "derived").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(yaml.safe_dump(
        {"id": "t", "version": 1, "fields": {},
         "entrypoints": [{"id": "g", "area": "dropbox/general"}],
         "pipeline": [{"id": "stamp", "uses": "engine.stamp"}]}))
    pair = corpus / "corpus" / "aaaaaaaaaaaa"
    pair.mkdir(parents=True)
    (pair / "transcript.md").write_text(TRANSCRIPT, encoding="utf-8")
    # run the REAL chunker → real spans + text in chunks.jsonl
    chunk_ast.run(pair, {"id": "chunk", "with": {"target_size": 40, "max_size": 400}},
                  pair / "transcript.md")
    sidecar.write(pair / "meta.yaml", {
        "doc_id": "aaaaaaaaaaaa", "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
        "status": "complete",
        "stages": [{"id": "received", "hash": "sha256:0", "fields": {}}],
        "artifacts": {"transcript": {"path": "./transcript.md"},
                      "chunks": {"path": "./chunks.jsonl"}}})
    return corpus, pair


@pytest.mark.asyncio
async def test_transcript_span_equals_text_through_the_fetch_path(tmp_path):
    """THE load-bearing test: the transcript fetched via the artifact endpoint,
    decoded UTF-8, satisfies transcript[span] == chunk.text — on chunks that sit
    AFTER multi-byte UTF-8 (umlauts), the offsets a German corpus hits."""
    corpus, pair = _corpus_with_real_chunks(tmp_path)
    records = [json.loads(l) for l in (pair / "chunks.jsonl").read_text().splitlines()]
    assert any(ord(ch) > 127 for ch in TRANSCRIPT[:records[-1]["span"][0]]), \
        "fixture must have multi-byte UTF-8 before the last chunk's span"

    client, _app = embed_client(corpus)
    try:
        raw = await client.artifact("aaaaaaaaaaaa", "transcript")
        transcript = raw.decode("utf-8")        # decode exactly as the chunker read it
        for rec in records:                     # every chunk, incl. those past umlauts
            start, end = rec["span"]
            assert transcript[start:end] == rec["text"]
    finally:
        await client.aclose()
