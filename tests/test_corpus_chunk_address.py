# tests/test_corpus_chunk_address.py
import hashlib
import json
from pathlib import Path

from shapes.corpus.builtins import chunk_ast

TRANSCRIPT = """\
# Wohnsituation

Ein Absatz über die Wohnung. Er ist kurz.

## Mietvertrag

Befristet? Ja, leider befristet auf zwei Jahre.

## Nebenkosten

Die Nebenkosten sind hoch.
"""


def _run(tmp_path, transcript=TRANSCRIPT, target=80, max_size=400):
    pair = tmp_path / "pair"
    pair.mkdir(parents=True)
    (pair / "transcript.md").write_text(transcript)
    stage = {"id": "chunk", "with": {"target_size": target, "max_size": max_size}}
    result = chunk_ast.run(pair, stage, pair / "transcript.md")
    records = [json.loads(line) for line in
               (pair / "chunks.jsonl").read_text().splitlines()]
    return records, transcript


def test_span_text_equals_source_slice(tmp_path):
    """transcript[span] == text, for every record (the contiguous invariant)."""
    records, transcript = _run(tmp_path)
    assert records
    for r in records:
        start, end = r["span"]
        assert transcript[start:end] == r["text"]
        assert r["contiguous"] is True


def test_embedder_input_equals_source_text(tmp_path):
    """The text the embedder would see is source text, not normalized text —
    custody text == source text. Locks the no-silent-normalization property."""
    records, transcript = _run(tmp_path)
    for r in records:
        assert r["text"] in transcript


def test_ast_path_tracks_heading_nesting(tmp_path):
    records, _ = _run(tmp_path)
    paths = {r["ast_path"] for r in records}
    assert "Wohnsituation" in paths
    assert "Wohnsituation > Mietvertrag" in paths
    assert "Wohnsituation > Nebenkosten" in paths


def test_ref_is_content_hash_not_sequential(tmp_path):
    records, _ = _run(tmp_path)
    for r in records:
        norm = " ".join(r["text"].split())
        expected = "c" + hashlib.sha256(
            (r["ast_path"] + "\x00" + norm).encode()).hexdigest()[:8]
        assert r["ref"] == expected
    assert len({r["ref"] for r in records}) == len(records)  # no collisions here


def test_ref_stable_across_rechunk(tmp_path):
    """Re-chunking unchanged input yields the same refs — the stability the
    index keys depend on."""
    first, _ = _run(tmp_path / "a")
    second, _ = _run(tmp_path / "b")
    assert [r["ref"] for r in first] == [r["ref"] for r in second]


def test_chunk_never_spans_two_sections(tmp_path):
    """Even with a target large enough to merge both sections, a chunk stays
    within one ast_path — the locator can't name the wrong section."""
    doc = "# A\n\nshort a.\n\n# B\n\nshort b.\n"
    records, _ = _run(tmp_path, transcript=doc, target=10000, max_size=10000)
    paths = [r["ast_path"] for r in records]
    assert "A" in paths and "B" in paths            # stayed separate
    for r in records:
        if r["ast_path"] == "A":
            assert "# B" not in r["text"]
        if r["ast_path"] == "B":
            assert "# A" not in r["text"]


def test_raises_on_transcript_with_no_blocks(tmp_path):
    import pytest

    from shapes.corpus.engine.errors import StageFailure
    with pytest.raises(StageFailure):
        _run(tmp_path, transcript="\n\n\n")


def test_oversized_block_splits_on_source_offsets(tmp_path):
    big = "# H\n\n" + ("x" * 1000) + "\n"
    records, transcript = _run(tmp_path, transcript=big, target=100, max_size=200)
    for r in records:
        start, end = r["span"]
        assert transcript[start:end] == r["text"]
        assert end - start <= 200
