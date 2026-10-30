# tests/test_corpus_serve_cmd.py
import yaml
from shapes.corpus.commands import serve
from tests.test_corpus_service_reads import FLOW


def test_serve_builds_an_app_for_a_corpus(tmp_path, monkeypatch):
    corpus = tmp_path / "c"
    (corpus / "derived").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(yaml.safe_dump(FLOW))

    started = {}

    def fake_run(app, host, port, **kw):
        started["host"] = host
        started["port"] = port

    monkeypatch.setattr(serve.uvicorn, "run", fake_run)
    serve.run(tmp_path, "corpus", [str(corpus), "--port", "9876"])
    assert started["host"] == "127.0.0.1"      # localhost only
    assert started["port"] == 9876
