import json
import sys
import yaml
import pytest
from shapes.corpus.engine import assert_inbox, sidecar
from shapes.corpus.engine.reactor import Engine

FLOW = """\
id: parking
version: 1
fields:
  tags: {type: set, of: string, by: operator}
entrypoints:
  - {id: general, area: dropbox/general, fields: {visibility: general}}
pipeline:
  - {id: stamp, uses: engine.stamp}
  - {id: normalize, uses: {dispatch_on: mime, routes: {text/plain: engine.wrap-md}},
     artifact: transcript}
  - id: datasheet
    uses: local.llm
    with: {prompt: "Summarize: ${artifact.transcript}"}
    fields:
      summary: {type: string, by: model}
      consent: {type: enum, values: [given, pending, declined], by: operator}
"""

ANSWER = {"fields": {"summary": "a short text"}, "proposed": {}, "confidence": {}}


@pytest.fixture
def world(tmp_path):
    machine = tmp_path
    (machine / "capabilities.yaml").write_text(yaml.safe_dump({"capabilities": {
        "local.llm": {"run": [sys.executable, "-c",
                              f"print({json.dumps(json.dumps(ANSWER))})"],
                      "reads": "stdin", "emits": "stdout"}}}))
    corpus = machine / "content" / "c"
    for sub in ("dropbox/general", "inbox"):
        (corpus / sub).mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(FLOW)
    return machine, corpus


def _run(engine, ticks=4):
    for _ in range(ticks):
        engine.tick()
    engine.drain()


def test_operator_field_parks_then_assert_resumes_to_complete(world):
    machine, corpus = world
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("the document body")
    _run(engine)
    parked = list((corpus / "working" / "datasheet").iterdir())
    assert len(parked) == 1
    doc = sidecar.read(parked[0] / "meta.yaml")
    assert doc["status"] == "parked@datasheet"
    assert doc["stages"][-1]["parked"] == ["consent"]
    doc_id = doc["doc_id"]

    from shapes.corpus.commands import assert_cmd
    assert_cmd.run(machine, "corpus", [str(corpus), doc_id,
                                       "consent=given", "tags+=housing,berlin"])
    _run(engine)
    bundle = corpus / "corpus" / doc_id
    assert bundle.exists()
    doc = sidecar.read(bundle / "meta.yaml")
    assert doc["status"] == "complete"
    last = doc["stages"][-1]
    assert last["id"] == "assert" and last["by"] == "operator" and last["via"] == "cli"
    assert last["fields"]["consent"] == "given"
    assert last["fields"]["tags"] == {"add": ["housing", "berlin"]}
    assert not list((corpus / "inbox").glob("*.assert.yaml"))   # consumed


def test_invalid_assert_goes_to_failed_inbox_with_reason(world):
    machine, corpus = world
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("body")
    _run(engine)
    doc_id = next((corpus / "working" / "datasheet").iterdir()).name
    bad = corpus / "inbox" / f"01J8X00000000000000000000-{doc_id}.assert.yaml"
    bad.write_text(yaml.safe_dump({
        "doc_id": doc_id, "by": "operator",
        "fields": {"consent": "absolutely"}}))     # not in the enum
    _run(engine)
    rejected = list((corpus / "failed" / "inbox").glob("*.assert.yaml"))
    assert len(rejected) == 1
    reason = rejected[0].with_suffix(".reason").read_text()
    assert "consent" in reason and "absolutely" in reason
    assert (corpus / "working" / "datasheet" / doc_id).exists()  # still parked


def test_assert_for_unknown_field_rejected(world):
    machine, corpus = world
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("body")
    _run(engine)
    doc_id = next((corpus / "working" / "datasheet").iterdir()).name
    target = assert_inbox.process(
        corpus, _write_assert(corpus, doc_id, {"made_up": 1}), engine.flow)
    assert target is None
    assert list((corpus / "failed" / "inbox").glob("*.reason"))


def test_assert_for_unknown_doc_rejected(world):
    machine, corpus = world
    engine = Engine(corpus, machine)
    path = _write_assert(corpus, "ffffffffffff", {"tags": {"add": ["x"]}})
    assert assert_inbox.process(corpus, path, engine.flow) is None


def _write_assert(corpus, doc_id, fields):
    path = corpus / "inbox" / f"01TEST0000000000000000000-{doc_id}.assert.yaml"
    path.write_text(yaml.safe_dump({"doc_id": doc_id, "by": "operator",
                                    "via": "test", "fields": fields}))
    return path


def test_rejection_never_overwrites_prior_rejection(world):
    machine, corpus = world
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("body")
    _run(engine)
    doc_id = next((corpus / "working" / "datasheet").iterdir()).name
    for _ in range(2):     # same filename rejected twice
        path = _write_assert(corpus, doc_id, {"made_up": 1})
        assert assert_inbox.process(corpus, path, engine.flow) is None
    rejected = list((corpus / "failed" / "inbox").glob("*.assert.yaml*"))
    assert len([p for p in rejected if not p.name.endswith(".reason")]) == 2


def test_filename_payload_doc_id_mismatch_rejected(world, tmp_path):
    """An assert file whose filename says doc_id A but payload says doc_id B
    must be rejected; the reason must mention both ids."""
    machine, corpus = world
    engine = Engine(corpus, machine)
    doc_id_a = "aaaaaaaaaaaa"
    doc_id_b = "bbbbbbbbbbbb"
    # Write assert file named for doc_id_a but payload claims doc_id_b
    path = corpus / "inbox" / f"01TEST0000000000000000000-{doc_id_a}.assert.yaml"
    path.write_text(yaml.safe_dump({
        "doc_id": doc_id_b, "by": "operator",
        "via": "test", "fields": {"tags": ["x"]}}))
    result = assert_inbox.process(corpus, path, engine.flow)
    assert result is None
    reasons = list((corpus / "failed" / "inbox").glob("*.reason"))
    assert len(reasons) == 1
    reason_text = reasons[0].read_text()
    assert doc_id_a in reason_text and doc_id_b in reason_text


# ---------------------------------------------------------------------------
# Writer-permission tests
# ---------------------------------------------------------------------------
from shapes.corpus.engine import assert_inbox as _assert_inbox_wp


def _wp_flow(by_decl):
    return {"id": "t", "version": 1,
            "fields": {"doc_type": {"type": "enum", "values": ["interview"],
                                    "by": by_decl}},
            "entrypoints": [{"id": "g", "area": "dropbox/general"}],
            "pipeline": [{"id": "stamp", "uses": "engine.stamp"}]}


def _wp_corpus(tmp_path, doc_id):
    from shapes.corpus.engine import sidecar as _sc
    corpus = tmp_path / "c"
    pair = corpus / "corpus" / doc_id
    pair.mkdir(parents=True)
    _sc.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
        "status": "complete",
        "stages": [{"id": "received", "hash": "sha256:0", "fields": {}}],
        "artifacts": {}})
    (corpus / "inbox").mkdir()
    return corpus


def test_operator_assert_on_model_only_field_rejected(tmp_path):
    corpus = _wp_corpus(tmp_path, "aaaaaaaaaaaa")
    af = corpus / "inbox" / "01J-aaaaaaaaaaaa.assert.yaml"
    af.write_text("doc_id: aaaaaaaaaaaa\nby: operator\nfields: {doc_type: interview}\n")
    result = _assert_inbox_wp.process(corpus, af, _wp_flow("model"))
    assert result is None                              # rejected
    reason = list((corpus / "failed" / "inbox").glob("*.reason"))[0].read_text()
    assert "operator may not write" in reason


def test_operator_assert_on_widened_field_accepted(tmp_path):
    corpus = _wp_corpus(tmp_path, "bbbbbbbbbbbb")
    af = corpus / "inbox" / "01J-bbbbbbbbbbbb.assert.yaml"
    af.write_text("doc_id: bbbbbbbbbbbb\nby: operator\nfields: {doc_type: interview}\n")
    result = _assert_inbox_wp.process(corpus, af, _wp_flow(["model", "operator"]))
    assert result is not None                          # accepted
