import yaml
from shapes.corpus.engine import sidecar
from shapes.corpus.engine.reactor import Engine

FLOW = """\
id: with-rule
version: 1
fields:
  consent: {type: enum, values: [given, pending, declined], by: operator}
rules:
  - {when: fields.consent == declined, do: retire}
entrypoints:
  - {id: general, area: dropbox/general, fields: {visibility: general}}
pipeline:
  - {id: stamp, uses: engine.stamp}
  - {id: normalize, uses: {dispatch_on: mime, routes: {text/plain: engine.wrap-md}},
     artifact: transcript}
"""


def _run(engine, ticks=4):
    for _ in range(ticks):
        engine.tick()
    engine.drain()


def test_consent_withdrawal_after_completion_retires(tmp_path):
    machine = tmp_path
    (machine / "capabilities.yaml").write_text("capabilities: {}\n")
    corpus = machine / "content" / "c"
    for sub in ("dropbox/general", "inbox"):
        (corpus / sub).mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(FLOW)

    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("interview body")
    _run(engine)
    doc_id = next((corpus / "corpus").iterdir()).name   # completed (no parked fields)

    from shapes.corpus.commands import assert_cmd
    assert_cmd.run(machine, "corpus", [str(corpus), doc_id, "consent=declined"])
    _run(engine)

    retired = corpus / "retired" / doc_id
    assert retired.exists()
    assert not (corpus / "corpus" / doc_id).exists()
    doc = sidecar.read(retired / "meta.yaml")
    assert doc["status"] == "retired"
    ids = [e["id"] for e in doc["stages"]]
    assert ids[-2:] == ["assert", "retired"]            # custody intact, in order
    assert (retired / "a.txt").exists()                 # retirement is a move,
    assert (retired / "transcript.md").exists()         # not a deletion


def test_second_assert_on_retired_doc_appends_no_second_retired_entry(tmp_path):
    machine = tmp_path
    (machine / "capabilities.yaml").write_text("capabilities: {}\n")
    corpus = machine / "content" / "c"
    for sub in ("dropbox/general", "inbox"):
        (corpus / sub).mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(FLOW)
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("interview body")
    _run(engine)
    doc_id = next((corpus / "corpus").iterdir()).name
    from shapes.corpus.commands import assert_cmd
    assert_cmd.run(machine, "corpus", [str(corpus), doc_id, "consent=declined"])
    _run(engine)
    assert_cmd.run(machine, "corpus", [str(corpus), doc_id, "consent=declined"])
    _run(engine)
    doc = sidecar.read(corpus / "retired" / doc_id / "meta.yaml")
    assert [e["id"] for e in doc["stages"]].count("retired") == 1
