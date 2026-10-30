# tests/test_corpus_doctype_override.py
from pathlib import Path

import yaml

from shapes.corpus.engine import assert_inbox, sidecar

FLOW = yaml.safe_load(
    (Path(__file__).parent.parent
     / "shapes/corpus/preview/corpus-example/flow.yaml").read_text())


def test_doc_type_declares_both_writers():
    decl = None
    for stage in FLOW["pipeline"]:
        if "fields" in stage and "doc_type" in stage["fields"]:
            decl = stage["fields"]["doc_type"]
    assert decl is not None
    assert decl["by"] == ["model", "operator"]


def test_operator_can_override_doc_type(tmp_path):
    corpus = tmp_path / "c"
    pair = corpus / "corpus" / "aaaaaaaaaaaa"
    pair.mkdir(parents=True)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": "aaaaaaaaaaaa", "flow": {"id": FLOW["id"],
        "version": FLOW["version"], "hash": "sha256:0"}, "status": "complete",
        "stages": [{"id": "classify", "fields": {"doc_type": "workshop"}}],
        "artifacts": {}})
    inbox = corpus / "inbox"
    inbox.mkdir()
    af = inbox / "01J-aaaaaaaaaaaa.assert.yaml"
    af.write_text("doc_id: aaaaaaaaaaaa\nby: operator\nfields: {doc_type: interview}\n")
    assert assert_inbox.process(corpus, af, FLOW) is not None
    doc = sidecar.read(pair / "meta.yaml")
    from shapes.corpus.engine.fold import fold
    assert fold(doc["stages"])["doc_type"] == "interview"
