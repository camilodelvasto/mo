# tests/test_corpus_order.py
from pathlib import Path

import yaml

from shapes.corpus.engine import sidecar
from shapes.corpus.engine.reactor import Engine

CAPS = "capabilities:\n  engine.stamp: {builtin: true}\n"

FLOW = {"id": "t", "version": 1,
        "fields": {"consent": {"type": "string", "by": "operator"}},
        "entrypoints": [{"id": "g", "area": "dropbox/general"}],
        "pipeline": [{"id": "stamp", "uses": "engine.stamp"}]}


def _engine(tmp_path):
    corpus = tmp_path / "c"
    (corpus / "inbox").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(yaml.safe_dump(FLOW))
    (tmp_path / "capabilities.yaml").write_text(CAPS)
    return Engine(corpus, tmp_path), corpus


def _complete_doc(corpus, doc_id):
    pair = corpus / "corpus" / doc_id
    pair.mkdir(parents=True)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:0"},
        "status": "complete",
        "stages": [{"id": "received", "hash": "sha256:0", "fields": {}}],
        "artifacts": {}})
    return pair


def test_retire_order_moves_bundle_to_retired(tmp_path):
    engine, corpus = _engine(tmp_path)
    _complete_doc(corpus, "aaaaaaaaaaaa")
    order = corpus / "inbox" / "01J-aaaaaaaaaaaa.order.yaml"
    order.write_text("doc_id: aaaaaaaaaaaa\nby: operator\naction: retire\n")
    engine.tick()
    engine.drain()
    assert (corpus / "retired" / "aaaaaaaaaaaa" / "meta.yaml").is_file()
    assert not (corpus / "corpus" / "aaaaaaaaaaaa").exists()
    doc = sidecar.read(corpus / "retired" / "aaaaaaaaaaaa" / "meta.yaml")
    assert doc["stages"][-1]["id"] == "retired"
    assert doc["stages"][-1]["by"] == "operator"
    assert not order.exists()           # consumed


def test_reprocess_order_refused_not_yet_implemented(tmp_path):
    engine, corpus = _engine(tmp_path)
    _complete_doc(corpus, "bbbbbbbbbbbb")
    order = corpus / "inbox" / "01J-bbbbbbbbbbbb.order.yaml"
    order.write_text("doc_id: bbbbbbbbbbbb\nby: operator\naction: reprocess\nfrom: stamp\n")
    engine.tick()
    engine.drain()
    assert not order.exists()                          # moved out of inbox
    rejected = list((corpus / "failed" / "inbox").glob("*.order.yaml"))
    assert rejected
    reason = rejected[0].with_suffix(".reason").read_text()
    assert "not yet implemented" in reason
    assert (corpus / "corpus" / "bbbbbbbbbbbb").exists()    # untouched
