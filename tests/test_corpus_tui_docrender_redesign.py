# tests/test_corpus_tui_docrender_redesign.py
from shapes.corpus.renderer.tui import docrender


def test_pipeline_rows_marks_actor_timing_and_contribution():
    log = {"entries": [
        {"id": "received", "entrypoint": "private"},
        {"id": "normalize", "model": {"name": "whisper-large-v3"},
         "output": {"artifact": "transcript"}, "meters": {"duration_ms": 86000}},
        {"id": "classify", "model": {"name": "llama-3.3-70b"},
         "meters": {"duration_ms": 4100, "confidence": 0.93},
         "fields": {"tipo_documento": "interview"}},
        {"id": "chunk", "capability": {"id": "engine.chunk-ast"},
         "meters": {"duration_ms": 1900, "chunks": 37}},
        {"id": "datasheet", "model": {"name": "llama-3.3-70b"},
         "parked": ["participants", "consent"]},
        {"id": "assert", "by": "operator", "via": "catalogue",
         "fields": {"consent": "given"}},
        {"id": "scan", "skipped": "fields.doc_type == report"}]}
    rows = docrender.pipeline_rows(log)
    assert rows[0].startswith("✓ received")
    assert "whisper-large-v3" in rows[1] and "86.0s" in rows[1] and "→ transcript" in rows[1]
    assert "llama-3.3-70b" in rows[2] and "0.93" in rows[2] and "tipo_documento: interview" in rows[2]
    assert "37 chunks" in rows[3]
    assert rows[4].startswith("◌ datasheet") and "parked: participants, consent" in rows[4]
    assert "operator" in rows[5] and "consent: given" in rows[5]
    assert rows[6].startswith("⊘ scan") and "skipped: fields.doc_type == report" in rows[6]


def test_distinct_sections_dedupes_in_order():
    chunks = [{"ast_path": "Über"}, {"ast_path": "Über"},
              {"ast_path": "Über > Miete"}, {"ast_path": "Über"}]
    assert docrender.distinct_sections(chunks) == ["Über", "Über > Miete"]


def test_doc_nav_nodes_four_readings_with_leaves_and_selection():
    nodes = docrender.doc_nav_nodes(
        field_names=["tipo_documento", "tema"],
        sections=["Über", "Miete"],
        stage_ids=["received", "classify"])
    assert [n["label"] for n in nodes] == ["document", "fields", "pipeline", "custody"]
    assert nodes[0]["select"] == ("reading", "document")
    assert nodes[0]["leaves"][0] == {"label": "Über", "select": ("section", "Über")}
    assert nodes[1]["leaves"][0] == {"label": "tipo_documento",
                                     "select": ("field", "tipo_documento")}
    assert nodes[2]["leaves"][1] == {"label": "classify", "select": ("stage", "classify")}
    assert nodes[3]["leaves"] == []          # custody has no outline


def test_field_trail_added_by_capability_on_date():
    doc = {"fields": {
        "tipo_documento": {"value": "informe",
            "provenance": {"stage": "classify", "by": "model", "capability": "local.llm",
                           "finished": "2026-06-02T09:42:55Z", "confidence": 0.91}},
        "consent": {"value": "given",
            "provenance": {"stage": "assert", "by": "operator", "at": "2026-06-04T16:20:00Z"}}}}
    rows = docrender.field_trail(doc)
    assert rows[0] == ("tipo_documento", "informe",
                       "added by local.llm on 02.06.2026 at 09:42 · 0.91")
    assert rows[1] == ("consent", "given",
                       "added by operator on 04.06.2026 at 16:20")   # operator, no conf
