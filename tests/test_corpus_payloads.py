# tests/test_corpus_payloads.py
import json
from pathlib import Path

from shapes.corpus.service import payloads

DECLARED = {"visibility", "doc_type", "consent", "tags", "summary", "project",
            "participants", "language"}

ROSETTA_STAGES = [
    {"id": "received", "entrypoint": "private", "hash": "sha256:3f9a21",
     "fields": {"visibility": "private"}},
    {"id": "stamp", "capability": {"id": "engine.stamp"}, "locality": "local",
     "meters": {"duration_ms": 740},
     "fields": {"source_name": "interview-04.opus", "mime": "audio/opus",
                "size": 18734221, "duration_s": 1842}},
    {"id": "classify", "capability": {"id": "local.llm"},
     "model": {"name": "llama-3.3-70b", "quant": "q4"}, "locality": "local",
     "meters": {"duration_ms": 4100, "confidence": 0.93},
     "fields": {"doc_type": "interview"}},
    {"id": "datasheet", "capability": {"id": "local.llm"}, "locality": "local",
     "meters": {"duration_ms": 7200, "confidence": {"participants": 0.71}},
     "fields": {"summary": "An interview about housing."},
     "proposed": {"participants": {"add": ["Interviewer", "Participant A"]},
                  "tags": {"add": ["housing", "tenancy-law", "berlin"]}},
     "parked": ["participants", "consent"]},
    {"id": "assert", "by": "operator", "via": "cli", "at": "2026-06-04T16:20:00Z",
     "fields": {"participants": {"add": ["Interviewer", "Participant A"]},
                "consent": "given",
                "tags": {"add": ["housing", "tenancy-law", "berlin"]}}},
    {"id": "assert", "by": "operator", "via": "cli", "at": "2026-06-14T11:02:00Z",
     "fields": {"tags": {"add": ["displacement"], "remove": ["berlin"]}}},
]


def _doc(stages, status="complete"):
    return {"doc_id": "3f9a21abcdef", "flow": {"id": "corpus-prep", "version": 4,
            "hash": "sha256:8c"}, "status": status, "stages": stages,
            "artifacts": {}}


def test_row_cells_are_declared_fields_with_coarse_by():
    row = payloads.build_row(_doc(ROSETTA_STAGES), DECLARED, pending=[])
    assert row["doc_id"] == "3f9a21abcdef"
    assert row["status"] == "complete"
    assert row["cells"]["doc_type"] == {"value": "interview", "by": "model"}
    assert row["cells"]["consent"] == {"value": "given", "by": "operator"}
    assert row["cells"]["tags"]["value"] == ["housing", "tenancy-law", "displacement"]
    assert "mime" not in row["cells"] and "size" not in row["cells"]


def test_row_proposals_carry_confidence_only_for_gated_fields():
    stages = ROSETTA_STAGES[:4]
    row = payloads.build_row(_doc(stages, status="parked@datasheet"), DECLARED,
                             pending=[])
    assert row["proposals"]["participants"]["add"] == ["Interviewer", "Participant A"]
    assert row["proposals"]["participants"]["confidence"] == 0.71
    assert row["proposals"]["tags"]["add"] == ["housing", "tenancy-law", "berlin"]
    assert "confidence" not in row["proposals"]["tags"]


def test_confirmed_proposals_drop_once_a_human_value_lands():
    row = payloads.build_row(_doc(ROSETTA_STAGES), DECLARED, pending=[])
    assert "proposals" not in row


def test_row_pending_marks_in_flight_asserts():
    row = payloads.build_row(_doc(ROSETTA_STAGES), DECLARED, pending=["consent"])
    assert row["pending"] == ["consent"]


def test_empty_proposals_and_pending_are_omitted():
    row = payloads.build_row(_doc(ROSETTA_STAGES), DECLARED, pending=[])
    assert "proposals" not in row
    assert "pending" not in row


def test_doc_payload_has_full_provenance_and_intrinsic():
    doc = payloads.build_doc(_doc(ROSETTA_STAGES), DECLARED)
    assert doc["fields"]["doc_type"]["value"] == "interview"
    prov = doc["fields"]["doc_type"]["provenance"]
    assert prov["stage"] == "classify"
    assert prov["by"] == "model"
    assert prov["capability"] == "local.llm"
    assert prov["confidence"] == 0.93
    assert doc["intrinsic"]["mime"] == "audio/opus"
    assert "mime" not in doc["fields"]


def test_custody_links_verify_the_chain(tmp_path):
    pair = tmp_path / "3f9a21abcdef"
    pair.mkdir()
    (pair / "transcript.md").write_text("redacted text")
    stages = [
        {"id": "received", "hash": "sha256:aa", "fields": {}},
        {"id": "normalize",
         "input": {"artifact": "original", "hash": "sha256:aa"},
         "output": {"artifact": "transcript", "hash": "sha256:bb"}, "fields": {}},
    ]
    doc = {"doc_id": "3f9a21abcdef", "flow": {"id": "t", "version": 1,
           "hash": "sha256:0"}, "status": "complete", "stages": stages,
           "artifacts": {"transcript": {"path": "./transcript.md"}}}
    links = payloads.build_custody(doc, pair)["links"]
    norm = next(l for l in links if l["stage"] == "normalize")
    assert norm["input"] == "sha256:aa" and norm["output"] == "sha256:bb"
    assert norm["verified"] is True
    assert norm["artifact_present"] is True


def test_chunks_payload_reads_records(tmp_path):
    pair = tmp_path / "3f9a21abcdef"
    pair.mkdir()
    (pair / "chunks.jsonl").write_text(
        json.dumps({"ref": "c043aa11", "ast_path": "a > b", "span": [10, 20],
                    "contiguous": True, "text": "ten chars!"}) + "\n")
    out = payloads.build_chunks(pair)
    assert out["chunks"][0]["ref"] == "c043aa11"
    assert out["chunks"][0]["size"] == 10
    assert out["chunks"][0]["vector"] is False
    assert out["chunks"][0]["contiguous"] is True
