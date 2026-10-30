# tests/test_corpus_order_cmd.py
import yaml

from shapes.corpus.commands import order_cmd


def _corpus(tmp_path):
    corpus = tmp_path / "c"
    (corpus / "inbox").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text("id: t\nversion: 1\n"
        "entrypoints: [{id: g, area: dropbox/general}]\n"
        "pipeline: [{id: stamp, uses: engine.stamp}]\n")
    return corpus


def test_order_retire_writes_file(tmp_path):
    corpus = _corpus(tmp_path)
    order_cmd.run(tmp_path, "corpus", [str(corpus), "aaaaaaaaaaaa", "retire"])
    files = list((corpus / "inbox").glob("*.order.yaml"))
    assert len(files) == 1
    payload = yaml.safe_load(files[0].read_text())
    assert payload == {"doc_id": "aaaaaaaaaaaa", "by": "operator", "action": "retire"}


def test_order_reprocess_with_from(tmp_path):
    corpus = _corpus(tmp_path)
    order_cmd.run(tmp_path, "corpus",
                  [str(corpus), "aaaaaaaaaaaa", "reprocess", "--from", "datasheet"])
    payload = yaml.safe_load(
        list((corpus / "inbox").glob("*.order.yaml"))[0].read_text())
    assert payload["action"] == "reprocess" and payload["from"] == "datasheet"
