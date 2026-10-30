import yaml
import pytest
from shapes.corpus.engine import sidecar
from shapes.corpus.engine.errors import CapabilityError, ContractError, IntegrityError
from shapes.corpus.engine.reactor import Engine


class RecordingObserver:
    def __init__(self):
        self.events = []
    def emit(self, event, **data):
        self.events.append((event, data))

FLOW = """\
id: builtins-only
version: 1
entrypoints:
  - {id: general, area: dropbox/general, fields: {visibility: general}}
  - {id: private, area: dropbox/private, fields: {visibility: private}}
pipeline:
  - {id: stamp, uses: engine.stamp}
  - id: normalize
    uses:
      dispatch_on: mime
      routes: {text/plain: engine.wrap-md, text/markdown: engine.passthrough}
    artifact: transcript
  - id: chunk
    uses: engine.chunk-ast
    with: {target_size: 512, max_size: 1024}
    artifact: chunks
"""


@pytest.fixture
def world(tmp_path):
    machine = tmp_path
    (machine / "capabilities.yaml").write_text("capabilities: {}\n")
    corpus = machine / "content" / "c"
    for sub in ("dropbox/general", "dropbox/private", "inbox"):
        (corpus / sub).mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(FLOW)
    return machine, corpus


def _run(engine, ticks=4):
    for _ in range(ticks):
        engine.tick()
    engine.drain()                # wait for the pool to finish submitted work


def test_engine_emits_lifecycle_events(world):
    machine, corpus = world
    rec = RecordingObserver()
    engine = Engine(corpus, machine, observer=rec)
    (corpus / "dropbox" / "general" / "a.txt").write_text("a body")
    _run(engine)
    names = [e for e, _ in rec.events]
    assert "dropped" in names
    assert "complete" in names
    # the engine emits regardless of any rendering level
    done = next(d for e, d in rec.events if e == "complete")
    assert "doc_id" in done


def test_txt_goes_dropbox_to_corpus(world):
    machine, corpus = world
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "note.txt").write_text("# hi\n\nbody text\n")
    _run(engine)
    bundles = list((corpus / "corpus").iterdir())
    assert len(bundles) == 1
    bundle = bundles[0]
    assert (bundle / "note.txt").exists()
    assert (bundle / "transcript.md").exists()
    assert (bundle / "chunks.jsonl").exists()
    doc = sidecar.read(bundle / "meta.yaml")
    assert doc["status"] == "complete"
    assert [e["id"] for e in doc["stages"]] == ["received", "stamp", "normalize", "chunk"]
    assert doc["stages"][0]["fields"]["visibility"] == "general"
    assert not (bundle / "flow.snapshot.yaml").exists()  # not copied into bundles
    assert (corpus / "dropbox" / "general" / "note.txt").exists() is False


def test_duplicate_drop_appends_event_not_a_second_document(world):
    machine, corpus = world
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "note.txt").write_text("same bytes")
    _run(engine)
    (corpus / "dropbox" / "private" / "copy.txt").write_text("same bytes")
    _run(engine)
    bundles = list((corpus / "corpus").iterdir())
    assert len(bundles) == 1
    doc = sidecar.read(bundles[0] / "meta.yaml")
    assert doc["stages"][-1]["id"] == "received-duplicate"
    assert doc["stages"][-1]["entrypoint"] == "private"
    assert doc["stages"][-1]["source_name"] == "copy.txt"


def test_anonymize_default_branch_is_fail_safe_by_source(tmp_path):
    # Two anonymize branches, exception-FIRST: source: news → passthrough (keep
    # names); default (no when) → anonymize. So a news doc keeps names, a general
    # doc is anonymized, and a doc with NO source (e.g. a pre-source-field doc
    # reprocessed) falls to the default and IS anonymized — privacy fails safe.
    # Pure config; no engine change.
    machine = tmp_path
    (machine / "capabilities.yaml").write_text("capabilities: {}\n")
    corpus = machine / "content" / "c"
    for sub in ("dropbox/general", "dropbox/news", "dropbox/legacy", "inbox"):
        (corpus / sub).mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text("""\
id: source-failsafe
version: 1
entrypoints:
  - {id: dropbox, area: dropbox/general, fields: {source: general}}
  - {id: dropbox-news, area: dropbox/news, fields: {source: news}}
  - {id: dropbox-legacy, area: dropbox/legacy}   # stamps no source (pre-field doc)
pipeline:
  - {id: stamp, uses: engine.stamp}
  - id: normalize
    uses: {dispatch_on: mime, routes: {text/plain: engine.wrap-md, text/markdown: engine.passthrough}}
    artifact: transcript
  - id: anonymize
    when: fields.source == news
    uses: engine.passthrough
    artifact: transcript
  - id: anonymize
    uses: engine.passthrough
    artifact: transcript
  - id: chunk
    uses: engine.chunk-ast
    with: {target_size: 512, max_size: 1024}
    artifact: chunks
""")
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "g.txt").write_text("# g\n\ngeneral body\n")
    (corpus / "dropbox" / "news" / "n.txt").write_text("# n\n\nnews body\n")
    (corpus / "dropbox" / "legacy" / "l.txt").write_text("# l\n\nlegacy body\n")
    _run(engine, ticks=8)

    by_ep = {}
    for b in (corpus / "corpus").iterdir():
        doc = sidecar.read(b / "meta.yaml")
        by_ep[doc["stages"][0]["entrypoint"]] = doc
    assert set(by_ep) == {"dropbox", "dropbox-news", "dropbox-legacy"}

    def anon(doc):
        return next(e for e in doc["stages"] if e["id"] == "anonymize")
    # news chose the exception branch (recorded when_matched); the others fell to
    # the default anonymize branch (no when, so no when_matched key).
    assert anon(by_ep["dropbox-news"]).get("when_matched") == "fields.source == news"
    assert "when_matched" not in anon(by_ep["dropbox"])          # general → anonymized
    assert "when_matched" not in anon(by_ep["dropbox-legacy"])   # no source → anonymized (fail-safe)


def test_missing_capability_refuses_startup(world):
    machine, corpus = world
    (corpus / "flow.yaml").write_text(FLOW.replace(
        "engine.wrap-md", "local.never-bound"))
    with pytest.raises(CapabilityError, match="local.never-bound"):
        Engine(corpus, machine)


def test_unroutable_mime_fails_the_pair_not_the_corpus(world, capsys):
    machine, corpus = world
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "data.json").write_text("{}")   # no route
    (corpus / "dropbox" / "general" / "fine.txt").write_text("ok body")
    _run(engine)
    assert len(list((corpus / "corpus").iterdir())) == 1              # fine.txt
    failed = list((corpus / "failed" / "normalize").iterdir())
    assert len(failed) == 1
    doc = sidecar.read(failed[0] / "meta.yaml")
    assert doc["status"] == "failed@normalize"
    assert "no route" in doc["stages"][-1]["failed"]
    # the failure surfaces on the watch console, not only in the sidecar
    err = capsys.readouterr().err
    assert "FAILED" in err and "normalize" in err and "no route" in err


def test_flow_edit_adopts_for_new_arrivals_only(world):
    machine, corpus = world
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("first body")
    _run(engine)
    edited = FLOW.replace("version: 1", "version: 2")
    (corpus / "flow.yaml").write_text(edited)
    (corpus / "dropbox" / "general" / "b.txt").write_text("second body")
    _run(engine)
    versions = sorted(
        sidecar.read(b / "meta.yaml")["flow"]["version"]
        for b in (corpus / "corpus").iterdir()
    )
    assert versions == [1, 2]


def test_foreign_sidecar_write_halts_pair_loudly(world, capsys):
    machine, corpus = world
    engine = Engine(corpus, machine)
    # build a parked-looking pair by hand, then corrupt it as a human would
    (corpus / "dropbox" / "general" / "a.txt").write_text("body here")
    _run(engine)
    bundle = next((corpus / "corpus").iterdir())
    meta = bundle / "meta.yaml"
    doc = yaml.safe_load(meta.read_text())
    doc["stages"].append({"id": "smuggled", "fields": {"x": 1}})
    meta.write_text(yaml.safe_dump(doc))      # forbidden write path
    engine.reevaluate(bundle)                 # any reaction touching the pair
    engine.drain()
    out = capsys.readouterr().err
    assert "outside the engine" in out
    assert sidecar.read(meta)["stages"][-1]["id"] == "smuggled"  # untouched, halted


def test_non_adjacent_branch_stages_refused_at_startup(world):
    machine, corpus = world
    broken = FLOW + "  - {id: stamp, uses: engine.passthrough}\n"
    (corpus / "flow.yaml").write_text(broken)        # stamp repeats after others
    with pytest.raises(ContractError, match="adjacent"):
        Engine(corpus, machine)


def test_unexpected_exception_releases_doc_loudly(world, capsys):
    machine, corpus = world
    engine = Engine(corpus, machine)

    def boom():
        raise RuntimeError("kaboom")

    engine._submit("deadbeefdead", boom)
    engine.drain()
    err = capsys.readouterr().err
    # ConsoleObserver truncates doc_id to 8 chars when rendering
    assert "deadbeef" in err and "kaboom" in err
    assert "deadbeefdead" not in engine._in_flight   # released, not wedged
    ran = []
    engine._submit("deadbeefdead", lambda: ran.append(1))
    engine.drain()
    assert ran == [1]                                # not halted either


def test_tick_survives_a_handler_exception(world, monkeypatch):
    # the worker pool is guarded; the tick loop must be too — one bad event
    # (a vanished file, an OSError mid-handler) cannot crash the watcher.
    machine, corpus = world
    rec = RecordingObserver()
    engine = Engine(corpus, machine, observer=rec)

    class _Ev:
        kind = "dropped"
        path = corpus / "dropbox" / "general" / "gone.txt"
        entrypoint = {"id": "general"}

    monkeypatch.setattr(engine.watcher, "tick", lambda: [_Ev()])
    monkeypatch.setattr(engine, "_on_drop",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaboom")))

    engine.tick()    # must NOT propagate — the loop survives the bad event

    reasons = [d["reason"] for e, d in rec.events if e == "error"]
    assert any("kaboom" in r for r in reasons)


# --- engine.rename: the original's name is a fact the flow may refuse to keep --

RENAME_FLOW = """\
id: renames
version: 1
entrypoints:
  - {id: drop, area: dropbox/general}
pipeline:
  - {id: rename, uses: engine.rename, with: {to: "${doc_id}"}, artifact: original}
  - {id: stamp, uses: engine.stamp}
  - id: normalize
    uses:
      dispatch_on: mime
      routes: {text/plain: engine.wrap-md}
    artifact: transcript
"""


def test_rename_before_stamp_keeps_the_dropped_name_out_of_the_bundle(world):
    machine, corpus = world
    (corpus / "flow.yaml").write_text(RENAME_FLOW)
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "Entrevista Juan Carlos.txt").write_text("body\n")
    _run(engine)
    bundles = list((corpus / "corpus").iterdir())
    assert len(bundles) == 1
    bundle = bundles[0]
    doc_id = bundle.name
    assert sorted(p.name for p in bundle.iterdir()) == [f"{doc_id}.txt", "meta.yaml", "transcript.md"]
    doc = sidecar.read_verified(bundle / "meta.yaml")      # custody chain still holds
    assert doc["status"] == "complete"
    assert [e["id"] for e in doc["stages"]] == ["received", "rename", "stamp", "normalize"]
    stamp = doc["stages"][2]
    assert stamp["fields"]["source_name"] == f"{doc_id}.txt"
    assert stamp["fields"]["mime"] == "text/plain"           # extension survived
    assert "Juan" not in (bundle / "meta.yaml").read_text()
    assert doc["artifacts"]["original"]["path"] == f"./{doc_id}.txt"


def test_duplicate_drop_under_a_renaming_flow_logs_no_name(world):
    machine, corpus = world
    (corpus / "flow.yaml").write_text(RENAME_FLOW)
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text("same bytes")
    _run(engine)
    (corpus / "dropbox" / "general" / "Entrevista Juan Carlos.txt").write_text("same bytes")
    _run(engine)
    bundle = next((corpus / "corpus").iterdir())
    doc = sidecar.read(bundle / "meta.yaml")
    assert doc["stages"][-1]["id"] == "received-duplicate"
    assert "source_name" not in doc["stages"][-1]
    assert "Juan" not in (bundle / "meta.yaml").read_text()
