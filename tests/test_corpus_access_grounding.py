import json
import textwrap
from pathlib import Path

import pytest
import yaml

from shapes.corpus.access import run_ask
from shapes.corpus.access.errors import AskError, CitationError
from shapes.corpus.engine import sidecar


def _machine(tmp_path, answer, dim=4):
    """Fake embed + fake claude. claude dumps its stdin prompt to prompt.txt so
    tests can assert what the model received. Returns (machine_root, prompt_path)."""
    emb = tmp_path / "fake_embed.py"
    emb.write_text(textwrap.dedent(f"""
        import sys, json
        for l in sys.stdin:
            l = l.strip()
            if l:
                c = json.loads(l)
                print(json.dumps({{"ref": c["ref"], "vector": [0.1]*{dim}, "dim": {dim}, "model": "fake"}}))
    """).strip())
    prompt_path = tmp_path / "prompt.txt"
    claude = tmp_path / "fake_claude.py"
    claude.write_text(textwrap.dedent(f"""
        import sys
        data = sys.stdin.read()
        open({str(prompt_path)!r}, "w").write(data)
        sys.stdout.write({answer!r})
    """).strip())
    table = {"capabilities": {
        "local.embed": {"run": ["python3", str(emb)], "reads": "stdin", "emits": "stdout"},
        "api.claude": {"run": ["python3", str(claude)], "reads": "stdin", "emits": "stdout"},
    }}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return tmp_path, prompt_path


_ASK = (
    "id: a\nversion: 1\nflow: ./flow.yaml\n"
    "index:\n  uses: local.embed\n"
    "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
    "    synthesize:\n      uses: api.claude\n      prompt: |\n"
    "        ${retrieved}\n        Pregunta: ${question}\n    check: citations\n"
)


def _corpus(tmp_path, ask_yaml=_ASK):
    corpus = tmp_path / "content" / "c"; corpus.mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\nask: ./ask.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\nfields: {}\npipeline: [{id: stamp, uses: engine.stamp}]\n")
    (corpus / "ask.yaml").write_text(ask_yaml)
    return corpus


def _bundle(corpus, doc_id, chunks):
    pair = corpus / "corpus" / doc_id; pair.mkdir(parents=True)
    (pair / "chunks.jsonl").write_text("".join(json.dumps(c) + "\n" for c in chunks))
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "complete", "stages": [{"id": "x", "fields": {}}], "artifacts": {}})


def test_default_grounding_is_one_and_renders_into_prompt(tmp_path):
    machine, prompt_path = _machine(tmp_path, "Según [aaaaaaaaaaaa:r1] sí.")
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿qué?")          # no grounding arg
    sent = prompt_path.read_text()
    assert "1.0" in sent                      # default value rendered
    assert "grounding" in sent.lower()        # directive present
    assert rec["answer"].startswith("Según")


def test_grounding_value_is_rendered(tmp_path):
    machine, prompt_path = _machine(tmp_path, "Según [aaaaaaaaaaaa:r1] sí.")
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    run_ask.run_ask(corpus, machine, "answer", "¿qué?", grounding=0.7)
    assert "0.7" in prompt_path.read_text()


def test_grounding_zero_forces_no_retrieval_and_no_gate(tmp_path):
    # answer has NO markers (pure model); with no sources, the gate must not fire
    machine, prompt_path = _machine(tmp_path, "Respuesta desde mi conocimiento, sin fuentes.")
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿qué?", grounding=0.0)
    assert rec["passages"] == []              # no retrieval at 0.0
    assert "${retrieved}" not in prompt_path.read_text()  # placeholder resolved (empty)
    assert rec["answer"].startswith("Respuesta")          # no CitationError


def test_citation_gate_still_fires_below_one(tmp_path):
    machine, _ = _machine(tmp_path, "Inventado [ffffffffffff:r9] sin fuente.")
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    with pytest.raises(CitationError):
        run_ask.run_ask(corpus, machine, "answer", "¿qué?", grounding=0.5)


def test_grounding_out_of_range_throws(tmp_path):
    machine, _ = _machine(tmp_path, "x")
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    for bad in (1.5, -0.1):
        with pytest.raises(AskError, match="grounding"):
            run_ask.run_ask(corpus, machine, "answer", "¿qué?", grounding=bad)


def test_ask_can_override_the_directive(tmp_path):
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
        "    grounding: 'NIVEL_PERSONALIZADO ${grounding} apegate a las fuentes'\n"
        "    synthesize:\n      uses: api.claude\n      prompt: '${retrieved} ${question}'\n"
    )
    machine, prompt_path = _machine(tmp_path, "ok [aaaaaaaaaaaa:r1]")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    run_ask.run_ask(corpus, machine, "answer", "¿qué?", grounding=0.6)
    sent = prompt_path.read_text()
    assert "NIVEL_PERSONALIZADO 0.6" in sent      # custom template + value used
