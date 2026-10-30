# tests/test_corpus_catalogue_cmd.py
import yaml

from shapes.corpus.commands import catalogue as catalogue_cmd

FLOW = {"id": "t", "version": 1,
        "fields": {"doc_type": {"type": "enum", "values": ["interview"], "by": "model"}},
        "entrypoints": [{"id": "g", "area": "dropbox/general"}],
        "pipeline": [{"id": "stamp", "uses": "engine.stamp"}]}

ASK = {"asks": [{"id": "find"},
                {"id": "answer"},
                {"id": "advisor", "retrieve": {"mode": "none"}, "grounding": 0.0}]}


def test_catalogue_cmd_builds_app_with_declared_columns(tmp_path, monkeypatch):
    """Catalogue opens on an ask-less corpus (ask: is optional in schema)."""
    corpus = tmp_path / "c"
    (corpus / "derived").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(yaml.safe_dump(FLOW))

    built = {}

    class _FakeApp:
        def __init__(self, corpus_dir, *, declared=None, asks=None, **kw):
            built["corpus_dir"] = corpus_dir
            built["declared"] = declared
            built["asks"] = asks
        def run(self):
            built["ran"] = True

    monkeypatch.setattr(catalogue_cmd, "CatalogueApp", _FakeApp)
    catalogue_cmd.run(tmp_path, "corpus", [str(corpus)])
    assert built["ran"] is True
    assert "doc_type" in built["declared"]
    assert built["asks"] == []


def test_catalogue_cmd_loads_asks_when_declared(tmp_path, monkeypatch):
    """When ask: is declared in corpus.yaml, ask ids are loaded and passed to CatalogueApp."""
    corpus = tmp_path / "c"
    (corpus / "derived").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\nask: ./ask.yaml\n")
    (corpus / "flow.yaml").write_text(yaml.safe_dump(FLOW))
    (corpus / "ask.yaml").write_text(yaml.safe_dump(ASK))

    built = {}

    class _FakeApp:
        def __init__(self, corpus_dir, *, declared=None, asks=None, ask_defaults=None, **kw):
            built["corpus_dir"] = corpus_dir
            built["declared"] = declared
            built["asks"] = asks
            built["ask_defaults"] = ask_defaults
        def run(self):
            built["ran"] = True

    monkeypatch.setattr(catalogue_cmd, "CatalogueApp", _FakeApp)
    catalogue_cmd.run(tmp_path, "corpus", [str(corpus)])
    assert built["ran"] is True
    assert built["asks"] == ["find", "answer", "advisor"]
    # each ask carries its DECLARED retrieval defaults; the undeclared ones fall back
    # to the engine's own (grounding 1.0, mode hybrid)
    assert built["ask_defaults"]["advisor"] == {"grounding": 0.0, "mode": "none"}
    assert built["ask_defaults"]["find"] == {"grounding": 1.0, "mode": "hybrid"}
