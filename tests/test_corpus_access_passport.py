import textwrap
from pathlib import Path

import pytest
import yaml

from shapes.corpus.access import passport
from shapes.corpus.access.errors import PassportError


def _machine(tmp_path, model="fake-1024", dim=4):
    binp = tmp_path / "fake_embed.py"
    binp.write_text(textwrap.dedent(f"""
        import sys, json
        chunks = [json.loads(l) for l in sys.stdin if l.strip()]
        for c in chunks:
            print(json.dumps({{"ref": c["ref"], "vector": [0.0]*{dim},
                               "dim": {dim}, "model": "{model}"}}))
    """).strip())
    table = {"capabilities": {"local.embed": {
        "run": ["python3", str(binp)], "reads": "stdin", "emits": "stdout"}}}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return tmp_path


def test_probe_discovers_model_and_dim(tmp_path):
    machine = _machine(tmp_path)
    corpus = tmp_path / "c"; corpus.mkdir()
    ident = passport.probe(corpus, machine)
    assert ident == {"capability": "local.embed", "model": "fake-1024", "dimension": 4}


def test_write_then_verify_matches(tmp_path):
    machine = _machine(tmp_path)
    corpus = tmp_path / "c"; (corpus / "index").mkdir(parents=True)
    ident = passport.probe(corpus, machine)
    passport.write(corpus, ident)
    assert passport.verify(corpus, machine) == ident  # no raise


def test_verify_throws_on_model_change(tmp_path):
    machine = _machine(tmp_path, model="model-A")
    corpus = tmp_path / "c"; (corpus / "index").mkdir(parents=True)
    passport.write(corpus, passport.probe(corpus, machine))
    machine2 = _machine(tmp_path, model="model-B")  # same dim, different model
    with pytest.raises(PassportError, match="model"):
        passport.verify(corpus, machine2)
