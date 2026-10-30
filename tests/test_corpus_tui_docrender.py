# tests/test_corpus_tui_docrender.py
from shapes.corpus.renderer.tui import docrender

DOC = {"doc_id": "3f9a21abcdef", "status": "complete",
       "flow": {"id": "corpus-prep", "version": 4, "hash": "sha256:8c"},
       "fields": {
           "doc_type": {"value": "interview",
                        "provenance": {"stage": "classify", "by": "model",
                                       "capability": "local.llm", "locality": "local",
                                       "confidence": 0.93}},
           "consent": {"value": "given",
                       "provenance": {"stage": "assert", "by": "operator", "via": "cli"}}},
       "intrinsic": {"mime": "audio/opus", "size": 18734221}}


def test_field_provenance_shows_the_contributing_entry():
    lines = docrender.field_provenance(DOC, "doc_type")
    text = "\n".join(lines)
    assert "classify" in text and "model" in text and "local.llm" in text and "0.93" in text


def test_custody_links_render_verified_and_present():
    payload = {"links": [
        {"stage": "normalize", "artifact": "transcript",
         "input": "sha256:aa", "output": "sha256:bb",
         "verified": True, "artifact_present": True}]}
    rows = docrender.custody_links(payload)
    assert "normalize" in rows[0] and "transcript" in rows[0]
    assert "✓" in rows[0]


def test_deleted_artifact_is_verified_and_absent_never_broken():
    # anonymize deleted the superseded bytes; the chain still verifies the hash.
    payload = {"links": [
        {"stage": "anonymize", "artifact": "transcript",
         "input": "sha256:bb", "output": "sha256:cc",
         "verified": True, "artifact_present": False}]}
    row = docrender.custody_links(payload)[0]
    assert "✓" in row                       # still verified
    assert "gone" in row.lower() or "absent" in row.lower()   # artifact absent
    assert "broken" not in row.lower()      # NEVER broken


def test_broken_chain_renders_broken():
    payload = {"links": [
        {"stage": "x", "artifact": "transcript", "input": "sha256:aa",
         "output": "sha256:bb", "verified": False, "artifact_present": True}]}
    assert "broken" in docrender.custody_links(payload)[0].lower()


# append to tests/test_corpus_tui_docrender.py
_CHUNKS = [
    {"ref": "c0001aaaa", "ast_path": "wohnsituation", "span": [0, 40],
     "contiguous": True, "size": 40, "vector": False},
    {"ref": "c0002bbbb", "ast_path": "wohnsituation > mietvertrag", "span": [40, 90],
     "contiguous": True, "size": 50, "vector": False},
    {"ref": "c0003cccc", "ast_path": "nebenkosten", "span": [90, 120],
     "contiguous": True, "size": 30, "vector": False}]


def test_chunk_rows_are_ref_path_size():
    rows = docrender.chunk_rows(_CHUNKS)
    assert rows[0][0] == "c0001aaaa" and rows[0][1] == "wohnsituation"
    assert rows[0][2] == "40"


def test_ast_path_filter_is_a_client_side_substring():
    hits = docrender.ast_path_filter(_CHUNKS, "miet")
    assert [c["ref"] for c in hits] == ["c0002bbbb"]      # contains, not where=
    assert docrender.ast_path_filter(_CHUNKS, "") == _CHUNKS   # empty = all


def test_chunk_inspector_shows_span_contiguity_ref_and_index_pending():
    lines = docrender.chunk_inspector(_CHUNKS[1])
    text = "\n".join(lines)
    assert "40" in text and "90" in text                 # span
    assert "text == source" in text and "✓" in text      # contiguity guarantee
    assert "c0002bbbb" in text                            # ref
    assert "index: not built" in text                    # NOT a per-chunk ✗
    assert "✗" not in text
