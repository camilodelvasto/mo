import json
import sys
import pytest
from shapes.corpus.engine import runner, sidecar
from shapes.corpus.engine.errors import StageFailure
from shapes.corpus.engine.observer import ConsoleObserver


class _Rec:
    def __init__(self):
        self.events = []

    def emit(self, event, **data):
        self.events.append((event, data))


def _pair(tmp_path, original_name="doc.txt", original_text="hello body"):
    pair = tmp_path / "working" / "stamp" / "aaaaaaaaaaaa"
    pair.mkdir(parents=True)
    original = pair / original_name
    original.write_text(original_text)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": "aaaaaaaaaaaa",
        "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "in-flight@stamp",
        "stages": [{"id": "received", "fields": {"visibility": "general"}}],
        "artifacts": {"meta": {"path": "./meta.yaml"},
                      "original": {"path": f"./{original_name}", "kept": True}},
    })
    return pair


def _py(code: str) -> list:
    return [sys.executable, "-c", code]


def test_builtin_stage_appends_custody_entry(tmp_path):
    pair = _pair(tmp_path)
    entry = runner.run_stage(pair, {"id": "stamp", "uses": "engine.stamp"}, {}, {}, ConsoleObserver(0))
    assert entry["id"] == "stamp"
    assert entry["fields"]["mime"] == "text/plain"
    assert entry["input"]["hash"] == entry["output"]["hash"]  # reads, never alters
    doc = sidecar.read(pair / "meta.yaml")
    assert [e["id"] for e in doc["stages"]] == ["received", "stamp"]


def test_external_stdout_capability_writes_artifact(tmp_path):
    pair = _pair(tmp_path)
    table = {"capabilities": {"local.upper": {
        "run": _py("import sys; print(sys.stdin.read().upper(), end='')"),
        "reads": "stdin", "emits": "stdout"}}}
    stage = {"id": "normalize", "uses": "local.upper", "artifact": "transcript"}
    entry = runner.run_stage(pair, stage, {}, table, ConsoleObserver(0))
    assert (pair / "transcript.md").read_text() == "HELLO BODY"
    assert entry["output"]["artifact"] == "transcript"
    doc = sidecar.read(pair / "meta.yaml")
    assert doc["artifacts"]["transcript"]["path"] == "./transcript.md"


def test_exit_code_maps_to_enum_field(tmp_path):
    pair = _pair(tmp_path)
    table = {"capabilities": {"local.scan": {
        "run": _py("raise SystemExit(0)"),
        "reads": "artifact", "emits": "exit_code", "map": {"0": "clean", "1": "infected"}}}}
    stage = {"id": "scan", "uses": "local.scan",
             "fields": {"scan": {"type": "enum", "values": ["clean", "infected"], "by": "model"}}}
    entry = runner.run_stage(pair, stage, {}, table, ConsoleObserver(0))
    assert entry["fields"]["scan"] == "clean"


def test_nonzero_exit_without_map_is_stage_failure(tmp_path):
    pair = _pair(tmp_path)
    table = {"capabilities": {"local.broken": {
        "run": _py("import sys; sys.stderr.write('boom'); raise SystemExit(2)"),
        "reads": "artifact", "emits": "stdout"}}}
    with pytest.raises(StageFailure, match="boom"):
        runner.run_stage(pair, {"id": "x", "uses": "local.broken"}, {}, table, ConsoleObserver(0))


def test_llm_stage_gates_on_confidence(tmp_path):
    pair = _pair(tmp_path)
    answer = {"fields": {"doc_type": "interview"}, "proposed": {"tags": ["housing"]},
              "confidence": {"doc_type": 0.6}}
    table = {"capabilities": {"local.llm": {
        "run": _py(f"print({json.dumps(json.dumps(answer))})"),
        "reads": "stdin", "emits": "stdout"}}}
    stage = {"id": "classify", "uses": "local.llm",
             "with": {"prompt": "Classify: ${fields.doc_type.values}"},
             "fields": {"doc_type": {"type": "enum",
                                     "values": ["interview", "other"],
                                     "by": "model", "confidence_min": 0.8}},
             "proposes": ["tags"]}
    entry = runner.run_stage(pair, stage, {}, table, ConsoleObserver(0))
    assert "doc_type" not in entry["fields"]          # below the gate
    assert entry["proposed"]["doc_type"] == "interview"
    assert entry["proposed"]["tags"] == ["housing"]
    assert entry["parked"] == ["doc_type"]
    assert entry["prompt"]["hash"].startswith("sha256:")


def test_optional_field_below_gate_proposes_without_parking(tmp_path):
    pair = _pair(tmp_path)
    answer = {"fields": {"audiencia": "Todas"}, "confidence": {"audiencia": 0.5}}
    table = {"capabilities": {"local.llm": {
        "run": _py(f"print({json.dumps(json.dumps(answer))})"),
        "reads": "stdin", "emits": "stdout"}}}
    stage = {"id": "characterize", "uses": "local.llm", "with": {"prompt": "x"},
             "fields": {"audiencia": {"type": "enum", "values": ["Flexible", "Todas"],
                                      "by": "model", "confidence_min": 0.8,
                                      "optional": True}}}
    entry = runner.run_stage(pair, stage, {}, table, ConsoleObserver(0))
    assert "audiencia" not in entry["fields"]          # below gate → not accepted
    assert entry["proposed"]["audiencia"] == "Todas"   # kept as a proposal
    assert "parked" not in entry                       # optional → never parks; doc completes


def test_llm_fenced_json_output_parses(tmp_path):
    pair = _pair(tmp_path)
    answer = {"fields": {"doc_type": "a"}, "confidence": {"doc_type": 0.9}}
    fenced = "```json\n" + json.dumps(answer) + "\n```"
    table = {"capabilities": {"local.llm": {
        "run": _py(f"import sys; sys.stdout.write({fenced!r})"),
        "reads": "stdin", "emits": "stdout"}}}
    stage = {"id": "classify", "uses": "local.llm", "with": {"prompt": "x"},
             "fields": {"doc_type": {"type": "enum", "values": ["a"], "by": "model",
                                     "confidence_min": 0.8}}}
    entry = runner.run_stage(pair, stage, {}, table, ConsoleObserver(0))
    assert entry["fields"]["doc_type"] == "a"


def test_llm_junk_output_is_stage_failure(tmp_path):
    pair = _pair(tmp_path)
    table = {"capabilities": {"local.llm": {
        "run": _py("print('Sure! Here is the JSON you asked for')"),
        "reads": "stdin", "emits": "stdout"}}}
    stage = {"id": "classify", "uses": "local.llm", "with": {"prompt": "x"},
             "fields": {"doc_type": {"type": "enum", "values": ["a"], "by": "model"}}}
    with pytest.raises(StageFailure):
        runner.run_stage(pair, stage, {}, table, ConsoleObserver(0))


def test_operator_field_parks_without_running_a_value(tmp_path):
    pair = _pair(tmp_path)
    answer = {"fields": {"summary": "two sentences"}, "confidence": {}}
    table = {"capabilities": {"local.llm": {
        "run": _py(f"print({json.dumps(json.dumps(answer))})"),
        "reads": "stdin", "emits": "stdout"}}}
    stage = {"id": "datasheet", "uses": "local.llm", "with": {"prompt": "x"},
             "fields": {"summary": {"type": "string", "by": "model"},
                        "consent": {"type": "enum", "values": ["given", "declined"],
                                    "by": "operator"}}}
    entry = runner.run_stage(pair, stage, {}, table, ConsoleObserver(0))
    assert entry["fields"]["summary"] == "two sentences"
    assert entry["parked"] == ["consent"]


def test_model_emitting_operator_field_is_loud(tmp_path):
    pair = _pair(tmp_path)
    answer = {"fields": {"consent": "given"}, "confidence": {}}
    table = {"capabilities": {"local.llm": {
        "run": _py(f"print({json.dumps(json.dumps(answer))})"),
        "reads": "stdin", "emits": "stdout"}}}
    stage = {"id": "datasheet", "uses": "local.llm", "with": {"prompt": "x"},
             "fields": {"consent": {"type": "enum", "values": ["given"], "by": "operator"}}}
    with pytest.raises(StageFailure, match="operator field"):
        runner.run_stage(pair, stage, {}, table, ConsoleObserver(0))


def test_dispatch_on_mime_routes_and_no_route_fails(tmp_path):
    pair = _pair(tmp_path)
    sidecar.append(pair / "meta.yaml", {"id": "stamp", "fields": {"mime": "text/plain"}})
    stage = {"id": "normalize", "uses": {"dispatch_on": "mime", "routes": {
        "text/plain": "engine.wrap-md"}}, "artifact": "transcript"}
    entry = runner.run_stage(pair, stage, {}, {}, ConsoleObserver(0))
    assert (pair / "transcript.md").exists()
    assert entry["capability"]["id"] == "engine.wrap-md"

    pair2 = _pair(tmp_path / "two")
    sidecar.append(pair2 / "meta.yaml", {"id": "stamp", "fields": {"mime": "application/zip"}})
    with pytest.raises(StageFailure, match="no route"):
        runner.run_stage(pair2, stage, {}, {}, ConsoleObserver(0))


def test_wildcard_mime_route(tmp_path):
    pair = _pair(tmp_path)
    sidecar.append(pair / "meta.yaml", {"id": "stamp", "fields": {"mime": "audio/opus"}})
    table = {"capabilities": {"local.noop": {
        "run": _py("print('transcribed', end='')"), "reads": "artifact", "emits": "stdout"}}}
    stage = {"id": "normalize", "uses": {"dispatch_on": "mime", "routes": {
        "audio/*": "local.noop"}}, "artifact": "transcript"}
    entry = runner.run_stage(pair, stage, {}, table, ConsoleObserver(0))
    assert (pair / "transcript.md").read_text() == "transcribed"


def test_capability_timeout_is_stage_failure(tmp_path):
    pair = _pair(tmp_path)
    table = {"capabilities": {"local.slow": {
        "run": _py("import time; time.sleep(5)"),
        "reads": "stdin", "emits": "stdout", "timeout": 0.3}}}
    with pytest.raises(StageFailure, match="timed out"):
        runner.run_stage(pair, {"id": "x", "uses": "local.slow"}, {}, table, ConsoleObserver(0))


def test_vanished_input_artifact_is_integrity_stop(tmp_path):
    from shapes.corpus.engine.errors import IntegrityError
    pair = _pair(tmp_path)
    (pair / "doc.txt").unlink()                      # artifact deleted mid-session
    with pytest.raises(IntegrityError, match="missing"):
        runner.run_stage(pair, {"id": "stamp", "uses": "engine.stamp"}, {}, {}, ConsoleObserver(0))


def test_builtin_stage_emits_stage_done(tmp_path):
    pair = _pair(tmp_path)
    rec = _Rec()
    runner.run_stage(pair, {"id": "stamp", "uses": "engine.stamp"}, {}, {}, rec)
    exec_events = [e for e in rec.events if e[0] in ("stage-done", "llm-call")]
    assert len(exec_events) == 1
    assert exec_events[0][0] == "stage-done"
    assert exec_events[0][1]["stage"] == "stamp"
    assert exec_events[0][1]["capability"] == "engine.stamp"


def test_failed_stage_emits_no_execution_line(tmp_path):
    pair = _pair(tmp_path)
    table = {"capabilities": {"local.broken": {
        "run": _py("import sys; sys.stderr.write('boom'); raise SystemExit(2)"),
        "reads": "artifact", "emits": "stdout"}}}
    rec = _Rec()
    with pytest.raises(StageFailure):
        runner.run_stage(pair, {"id": "x", "uses": "local.broken"}, {}, table, rec)
    assert [e for e in rec.events if e[0] in ("stage-done", "llm-call")] == []


def test_llm_stage_emits_llm_call_with_prompt_and_response(tmp_path):
    pair = _pair(tmp_path)
    answer = {"fields": {"doc_type": "interview"}, "proposed": {}, "confidence": {"doc_type": 0.9}}
    table = {"capabilities": {"local.llm": {
        "run": _py(f"print({json.dumps(json.dumps(answer))})"),
        "reads": "stdin", "emits": "stdout"}}}
    stage = {"id": "classify", "uses": "local.llm",
             "with": {"prompt": "Classify: ${fields.doc_type.values}"},
             "fields": {"doc_type": {"type": "enum",
                                     "values": ["interview", "other"],
                                     "by": "model", "confidence_min": 0.8}}}
    rec = _Rec()
    runner.run_stage(pair, stage, {}, table, rec)
    exec_events = [e for e in rec.events if e[0] in ("stage-done", "llm-call")]
    assert len(exec_events) == 1
    assert exec_events[0][0] == "llm-call"
    assert exec_events[0][1]["stage"] == "classify"
    assert exec_events[0][1]["capability"] == "local.llm"
    # the ephemeral text reaches the observer: the resolved prompt and the raw
    # model response (which carries the classification) are both present
    assert "Classify:" in exec_events[0][1]["prompt"]
    assert "interview" in exec_events[0][1]["response"]


def test_gated_field_records_confidence_in_meters(monkeypatch, tmp_path):
    """A model field below its confidence_min lands in proposed: and its
    confidence is recorded in meters.confidence for the catalogue to show."""
    pair = tmp_path / "pair"
    pair.mkdir()
    (pair / "transcript.md").write_text("some text")
    from shapes.corpus.engine import sidecar
    sidecar.write(pair / "meta.yaml", {
        "doc_id": "aaaaaaaaaaaa",
        "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "in-flight@datasheet", "stages": [
            {"id": "received", "hash": "sha256:00", "fields": {}},
        ],
        "artifacts": {"transcript": {"path": "./transcript.md"}},
    })
    stage = {"id": "datasheet", "uses": "local.llm", "artifact": None,
             "with": {"prompt": "p"},
             "fields": {"doc_type": {"type": "enum", "values": ["interview"],
                                     "by": "model", "confidence_min": 0.8}}}

    def fake_spawn(pair_dir, st, binding, input_path):
        # raw_fields, proposed, confidence, output, meters, prompt_block, prompt_text, response_text
        return ({"doc_type": "interview"}, {}, {"doc_type": 0.71}, None,
                {"duration_ms": 5}, None, None, None)

    monkeypatch.setattr(runner, "_spawn", fake_spawn)
    monkeypatch.setattr(runner.capabilities, "resolve", lambda *a, **k: {})
    entry = runner.run_stage(pair, stage, {}, {}, _Rec())
    assert "doc_type" in entry.get("proposed", {})
    assert entry["meters"]["confidence"]["doc_type"] == 0.71


def test_list_by_field_is_asked_of_the_model():
    """A by: [model, operator] field must appear in the model's output
    contract — the model is the one that classifies it."""
    from shapes.corpus.engine.runner import _output_contract
    stage = {"id": "classify",
             "fields": {"doc_type": {"type": "enum", "values": ["interview"],
                                     "by": ["model", "operator"]}}}
    assert "fields.doc_type" in _output_contract(stage)


def test_list_by_field_is_model_writable_and_gates(tmp_path):
    """A by: [model, operator] field is the model's to classify through its
    gate (and the operator's to override later). Above the gate it LANDS as a
    model field; it is NOT treated as operator-only and does not park."""
    pair = _pair(tmp_path)
    answer = {"fields": {"doc_type": "interview"},
              "confidence": {"doc_type": 0.95}}
    table = {"capabilities": {"local.llm": {
        "run": _py(f"print({json.dumps(json.dumps(answer))})"),
        "reads": "stdin", "emits": "stdout"}}}
    stage = {"id": "classify", "uses": "local.llm",
             "with": {"prompt": "Classify: ${fields.doc_type.values}"},
             "fields": {"doc_type": {"type": "enum",
                                     "values": ["interview", "other"],
                                     "by": ["model", "operator"],
                                     "confidence_min": 0.8}}}
    entry = runner.run_stage(pair, stage, {}, table, ConsoleObserver(0))
    assert entry["fields"]["doc_type"] == "interview"   # model wrote it, above gate
    assert "parked" not in entry                        # not operator-only
