import sys
import yaml
from shapes.corpus.engine import sidecar
from shapes.corpus.engine.reactor import Engine

FLOW = """\
id: repairable
version: 1
entrypoints:
  - {id: general, area: dropbox/general, fields: {visibility: general}}
pipeline:
  - {id: stamp, uses: engine.stamp}
  - {id: normalize, uses: {dispatch_on: mime, routes: {text/plain: local.flaky}},
     artifact: transcript}
"""


def _bind(machine, code):
    (machine / "capabilities.yaml").write_text(yaml.safe_dump({"capabilities": {
        "local.flaky": {"run": [sys.executable, "-c", code],
                        "reads": "stdin", "emits": "stdout"}}}))


def _run(engine, ticks=4):
    for _ in range(ticks):
        engine.tick()
    engine.drain()


def test_restart_reruns_failed_after_repair(tmp_path):
    machine = tmp_path
    _bind(machine, "import sys; sys.stderr.write('tool broken'); raise SystemExit(2)")
    corpus = machine / "content" / "c"
    (corpus / "dropbox" / "general").mkdir(parents=True)
    (corpus / "inbox").mkdir()
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(FLOW)

    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("body text")
    _run(engine)
    failed = list((corpus / "failed" / "normalize").iterdir())
    assert len(failed) == 1                       # the tool rejected the input

    _bind(machine, "import sys; print(sys.stdin.read().upper(), end='')")  # repaired
    engine2 = Engine(corpus, machine)             # --restart implies a fresh start
    engine2.restart_failed()
    engine2.drain()
    doc_id = failed[0].name
    bundle = corpus / "corpus" / doc_id
    assert bundle.exists()
    doc = sidecar.read(bundle / "meta.yaml")
    assert doc["status"] == "complete"
    ids = [e["id"] for e in doc["stages"]]
    assert ids.count("normalize") == 2            # the failure entry, then the run
    assert (bundle / "transcript.md").read_text() == "BODY TEXT"


ASSERTABLE_FLOW = """\
id: repairable
version: 1
fields:
  tags: {type: set, of: string, by: operator}
entrypoints:
  - {id: general, area: dropbox/general, fields: {visibility: general}}
pipeline:
  - {id: stamp, uses: engine.stamp}
  - {id: normalize, uses: {dispatch_on: mime, routes: {text/plain: local.flaky}},
     artifact: transcript}
"""


def test_assert_on_failed_doc_triggers_restart(tmp_path):
    # An operator who edits fields on a failed doc (via the catalogue) signals
    # "I've looked at this — try again". The assert is recorded AND the failed
    # stage re-runs, the same recovery --restart performs for one pair.
    machine = tmp_path
    _bind(machine, "import sys; sys.stderr.write('tool broken'); raise SystemExit(2)")
    corpus = machine / "content" / "c"
    (corpus / "dropbox" / "general").mkdir(parents=True)
    (corpus / "inbox").mkdir()
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(ASSERTABLE_FLOW)

    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("body text")
    _run(engine)
    failed = list((corpus / "failed" / "normalize").iterdir())
    assert len(failed) == 1
    doc_id = failed[0].name

    _bind(machine, "import sys; print(sys.stdin.read().upper(), end='')")  # repaired
    engine2 = Engine(corpus, machine)
    from shapes.corpus.commands import assert_cmd
    assert_cmd.run(machine, "corpus", [str(corpus), doc_id, "tags+=interconexion"])
    _run(engine2)

    bundle = corpus / "corpus" / doc_id
    assert bundle.exists()                            # moved out of failed/, completed
    assert not (corpus / "failed" / "normalize" / doc_id).exists()
    doc = sidecar.read(bundle / "meta.yaml")
    assert doc["status"] == "complete"
    ids = [e["id"] for e in doc["stages"]]
    assert ids.count("normalize") == 2               # failure entry, then the rerun
    assert "assert" in ids                            # the operator edit is recorded
    assert (bundle / "transcript.md").read_text() == "BODY TEXT"


def test_restart_halts_tampered_failed_pair(tmp_path, capsys):
    machine = tmp_path
    _bind(machine, "import sys; sys.stderr.write('broken'); raise SystemExit(2)")
    corpus = machine / "content" / "c"
    (corpus / "dropbox" / "general").mkdir(parents=True)
    (corpus / "inbox").mkdir()
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(FLOW)
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("body text")
    _run(engine)
    failed = next((corpus / "failed" / "normalize").iterdir())
    (failed / "a.txt").write_text("tampered")        # swap the original
    _bind(machine, "import sys; print(sys.stdin.read().upper(), end='')")
    engine2 = Engine(corpus, machine)
    engine2.restart_failed()
    engine2.drain()
    assert "HALTED" in capsys.readouterr().err
    # restart_failed moves the pair to working/normalize BEFORE _resume_job
    # runs verify_chain.  The IntegrityError halts the job there; the pair
    # stays in working/normalize awaiting operator intervention.
    assert (corpus / "working" / "normalize" / failed.name).exists()


def test_restart_leaves_parked_pairs_alone(tmp_path):
    machine = tmp_path
    (machine / "capabilities.yaml").write_text("capabilities: {}\n")
    corpus = machine / "content" / "c"
    (corpus / "dropbox" / "general").mkdir(parents=True)
    (corpus / "inbox").mkdir()
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\n"
        "entrypoints: [{id: general, area: dropbox/general}]\n"
        "pipeline: [{id: stamp, uses: engine.stamp}]\n")
    pair = corpus / "working" / "datasheet" / "aaaaaaaaaaaa"
    pair.mkdir(parents=True)
    (pair / "flow.snapshot.yaml").write_text((corpus / "flow.yaml").read_text())
    sidecar.write(pair / "meta.yaml", {
        "doc_id": "aaaaaaaaaaaa", "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "parked@datasheet",
        "stages": [{"id": "received", "fields": {}},
                   {"id": "datasheet", "fields": {}, "parked": ["consent"]}],
        "artifacts": {"meta": {"path": "./meta.yaml"}},
    })
    engine = Engine(corpus, machine)
    engine.restart_failed()
    engine.drain()
    doc = sidecar.read(pair / "meta.yaml")
    assert doc["status"] == "parked@datasheet"    # waiting for an assert, not restart
