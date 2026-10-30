# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import sys
import yaml
import pytest
from shapes.corpus.engine import sidecar
from shapes.corpus.engine.errors import ContractError
from shapes.corpus.engine.reactor import Engine

FLOW_V1 = """\
id: reprocessable
version: 1
entrypoints:
  - {id: general, area: dropbox/general, fields: {visibility: general}}
pipeline:
  - {id: stamp, uses: engine.stamp}
  - {id: normalize, uses: {dispatch_on: mime, routes: {text/plain: engine.wrap-md}},
     artifact: transcript}
  - {id: chunk, uses: engine.chunk-ast, with: {target_size: 512, max_size: 1024},
     artifact: chunks}
"""

# v2 inserts a `recheck` stage (a builtin, no capability binding needed) between
# normalize and chunk. NOTE: the "  - {id: chunk," literal must match FLOW_V1
# exactly — if FLOW_V1's chunk line is reindented, this replace silently no-ops.
FLOW_V2 = FLOW_V1.replace(
    "  - {id: chunk,",
    "  - {id: recheck, uses: engine.passthrough, artifact: transcript}\n"
    "  - {id: chunk,").replace("version: 1", "version: 2")
assert "recheck" in FLOW_V2 and "version: 2" in FLOW_V2   # guard the replace

# A flow where `transform` rewrites the transcript that `normalize` produced.
FLOW_REWRITE = """\
id: rewriter
version: 1
entrypoints:
  - {id: general, area: dropbox/general, fields: {visibility: general}}
pipeline:
  - {id: stamp, uses: engine.stamp}
  - {id: normalize, uses: {dispatch_on: mime, routes: {text/plain: engine.wrap-md}},
     artifact: transcript}
  - {id: transform, uses: local.upper, artifact: transcript}
  - {id: chunk, uses: engine.chunk-ast, with: {target_size: 512, max_size: 1024},
     artifact: chunks}
"""


def _bind_upper(machine):
    (machine / "capabilities.yaml").write_text(yaml.safe_dump({"capabilities": {
        "local.upper": {"run": [sys.executable, "-c",
                                "import sys; print(sys.stdin.read().upper(), end='')"],
                        "reads": "stdin", "emits": "stdout"}}}))


def _corpus(tmp_path, flow=FLOW_V1):
    machine = tmp_path
    (machine / "capabilities.yaml").write_text("capabilities: {}\n")
    corpus = machine / "content" / "c"
    (corpus / "dropbox" / "general").mkdir(parents=True)
    (corpus / "inbox").mkdir()
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(flow)
    return machine, corpus


def _run(engine, ticks=4):
    for _ in range(ticks):
        engine.tick()
    engine.drain()


def _complete_one(machine, corpus, body="some body text"):
    engine = Engine(corpus, machine)
    (corpus / "dropbox" / "general" / "a.txt").write_text(body)
    _run(engine)
    bundle = next((corpus / "corpus").iterdir())
    return bundle.name


def test_reprocess_from_stage_reruns_through_new_stage(tmp_path):
    machine, corpus = _corpus(tmp_path)
    doc_id = _complete_one(machine, corpus)
    bundle = corpus / "corpus" / doc_id
    assert (bundle / "chunks.jsonl").exists()
    transcript_before = (bundle / "transcript.md").read_bytes()   # upstream of recheck
    chunks_ino_before = (bundle / "chunks.jsonl").stat().st_ino    # downstream of recheck

    (corpus / "flow.yaml").write_text(FLOW_V2)         # insert `recheck`
    engine = Engine(corpus, machine)                   # picks up v2
    done = engine.reprocess([doc_id], "recheck")
    engine.drain()
    assert done == 1

    assert bundle.exists()                             # completed again
    # the reused upstream artifact was NOT rewritten (passthrough on the same file)
    assert (bundle / "transcript.md").read_bytes() == transcript_before
    # the dropped downstream artifact was deleted and regenerated (new inode)
    assert (bundle / "chunks.jsonl").stat().st_ino != chunks_ino_before
    doc = sidecar.read(bundle / "meta.yaml")
    ids = [e["id"] for e in doc["stages"]]
    assert ids.count("recheck") == 1                   # the new stage ran
    assert ids.count("chunk") == 1                     # downstream re-ran (rewound)
    assert "reprocessed" in ids                        # breadcrumb present
    crumb = next(e for e in doc["stages"] if e["id"] == "reprocessed")
    assert crumb["from"] == "recheck"
    assert crumb["prior_hash"].startswith("sha256:")
    assert crumb["prior_flow_version"] == 1
    assert crumb["flow_version"] == 2
    assert doc["flow"]["version"] == 2                 # re-pinned


def test_reprocess_unknown_from_refuses(tmp_path):
    machine, corpus = _corpus(tmp_path)
    doc_id = _complete_one(machine, corpus)
    engine = Engine(corpus, machine)
    with pytest.raises(ContractError, match="nope"):
        engine.reprocess([doc_id], "nope")
    doc = sidecar.read(corpus / "corpus" / doc_id / "meta.yaml")
    assert doc["status"] == "complete"
    assert "reprocessed" not in [e["id"] for e in doc["stages"]]


def test_reprocess_skips_unknown_doc(tmp_path):
    machine, corpus = _corpus(tmp_path)
    _complete_one(machine, corpus)
    engine = Engine(corpus, machine)
    done = engine.reprocess(["ffffffffffff"], None)
    engine.drain()
    assert done == 0


def test_reprocess_skips_doc_with_broken_chain(tmp_path):
    machine, corpus = _corpus(tmp_path)
    doc_id = _complete_one(machine, corpus)
    (corpus / "corpus" / doc_id / "transcript.md").unlink()   # corrupt: kept artifact gone
    engine = Engine(corpus, machine)
    done = engine.reprocess([doc_id], "chunk")
    engine.drain()
    assert done == 0
    assert (corpus / "corpus" / doc_id).exists()


def test_reprocess_full_rerun_no_from(tmp_path):
    machine, corpus = _corpus(tmp_path)
    doc_id = _complete_one(machine, corpus)
    engine = Engine(corpus, machine)
    done = engine.reprocess([doc_id], None)
    engine.drain()
    assert done == 1
    doc = sidecar.read(corpus / "corpus" / doc_id / "meta.yaml")
    ids = [e["id"] for e in doc["stages"]]
    assert ids.count("stamp") == 1 and ids.count("normalize") == 1 and ids.count("chunk") == 1
    crumb = next(e for e in doc["stages"] if e["id"] == "reprocessed")
    assert crumb["from"] is None


def test_engine_resume_false_does_not_autoresume_working(tmp_path):
    from shapes.corpus.engine import identity as _identity
    machine, corpus = _corpus(tmp_path)
    # Plant a synthetic pair in working/stamp — exactly as _on_drop would (minus the
    # original file content), with a valid snapshot so _resume_job doesn't crash.
    pair = corpus / "working" / "stamp" / "aaaaaaaaaaaa"
    pair.mkdir(parents=True)
    (pair / "flow.snapshot.yaml").write_text((corpus / "flow.yaml").read_text())
    sidecar.write(pair / "meta.yaml", {
        "doc_id": "aaaaaaaaaaaa",
        "flow": {"id": "reprocessable", "version": 1, "hash": "sha256:00"},
        "status": "in-flight@stamp",
        "stages": [{"id": "received", "fields": {}}],
        "artifacts": {"meta": {"path": "./meta.yaml"}},
    })

    default = Engine(corpus, machine)                 # resume=True
    assert default._futures                            # auto-resumed the working pair
    default.drain()

    # Plant the synthetic pair again in working/ and verify resume=False skips it.
    pair2 = corpus / "working" / "stamp" / "bbbbbbbbbbbb"
    pair2.mkdir(parents=True, exist_ok=True)
    (pair2 / "flow.snapshot.yaml").write_text((corpus / "flow.yaml").read_text())
    sidecar.write(pair2 / "meta.yaml", {
        "doc_id": "bbbbbbbbbbbb",
        "flow": {"id": "reprocessable", "version": 1, "hash": "sha256:00"},
        "status": "in-flight@stamp",
        "stages": [{"id": "received", "fields": {}}],
        "artifacts": {"meta": {"path": "./meta.yaml"}},
    })
    noresume = Engine(corpus, machine, resume=False)
    assert not noresume._futures                       # did NOT auto-resume
    noresume.drain()


def test_in_place_rewrite_keeps_custody_chain_intact(tmp_path):
    # A stage that reads AND writes the same artifact (transform rewrites the
    # transcript) must record the PRE-run input hash, not the rewritten one —
    # else the custody chain breaks on the next read.
    machine, corpus = _corpus(tmp_path, flow=FLOW_REWRITE)
    _bind_upper(machine)
    doc_id = _complete_one(machine, corpus)
    sidecar.verify_chain(corpus / "corpus" / doc_id)   # raises IntegrityError if broken
    doc = sidecar.read(corpus / "corpus" / doc_id / "meta.yaml")
    norm = next(e for e in doc["stages"] if e["id"] == "normalize")
    tr = next(e for e in doc["stages"] if e["id"] == "transform")
    assert tr["input"]["hash"] == norm["output"]["hash"]   # input == normalize's output
    assert tr["output"]["hash"] != tr["input"]["hash"]     # it DID rewrite


def test_reprocess_skips_when_reused_artifact_was_rewritten(tmp_path):
    machine, corpus = _corpus(tmp_path, flow=FLOW_REWRITE)
    _bind_upper(machine)
    doc_id = _complete_one(machine, corpus)           # transcript is now UPPERCASED
    engine = Engine(corpus, machine, resume=False)
    # rewind to transform: keeps normalize (lowercase hash) but disk is uppercase
    done = engine.reprocess([doc_id], "transform")
    engine.drain()
    assert done == 0                                  # skipped, not stranded
    doc = sidecar.read(corpus / "corpus" / doc_id / "meta.yaml")
    assert doc["status"] == "complete"                # untouched
    assert "reprocessed" not in [e["id"] for e in doc["stages"]]


def test_reprocess_command_refuses_all_docs_without_flag(tmp_path, capsys):
    from shapes.corpus.commands import reprocess as cmd
    with pytest.raises(SystemExit):
        cmd.run(tmp_path, "corpus", ["some/corpus"])
    assert "--all" in capsys.readouterr().err


def test_reprocess_command_refuses_all_flag_with_doc_ids(tmp_path, capsys):
    from shapes.corpus.commands import reprocess as cmd
    with pytest.raises(SystemExit):
        cmd.run(tmp_path, "corpus", ["some/corpus", "aaaaaaaaaaaa", "--all"])
    assert "--all" in capsys.readouterr().err
