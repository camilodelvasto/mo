# tests/test_corpus_access_provenance.py — run_ask attaches a provenance block
# (timing always; model/usage/cost/prompt when the capability emits an envelope).
import json
import textwrap
from pathlib import Path

import pytest
import yaml

from shapes.corpus.access import run_ask
from shapes.corpus.engine import sidecar


def _machine(tmp_path, *, envelope: bool, answer: str, dim=4):
    """Fake embed + fake claude. When envelope=True the fake claude emits the moui
    synthesis envelope and the binding declares emits: envelope; otherwise plain
    text on stdout (the legacy path)."""
    emb = tmp_path / "fake_embed.py"
    emb.write_text(textwrap.dedent(f"""
        import sys, json
        for l in sys.stdin:
            l = l.strip()
            if l:
                c = json.loads(l)
                print(json.dumps({{"ref": c["ref"], "vector": [0.1]*{dim}, "dim": {dim}, "model": "fake"}}))
    """).strip())

    claude = tmp_path / "fake_claude.py"
    if envelope:
        env = {"answer": answer, "model": "claude-opus-4-8",
               "usage": {"input_tokens": 1234, "output_tokens": 480,
                         "cache_read_input_tokens": 21434},
               "cost_usd": 0.046, "duration_ms": 4103}
        claude.write_text(textwrap.dedent(f"""
            import sys
            sys.stdin.read()
            sys.stdout.write({json.dumps(env)!r})
        """).strip())
        emits = "envelope"
    else:
        claude.write_text(textwrap.dedent(f"""
            import sys
            sys.stdin.read()
            sys.stdout.write({answer!r})
        """).strip())
        emits = "stdout"

    uses = "api.claude-json" if envelope else "api.claude"
    table = {"capabilities": {
        "local.embed": {"run": ["python3", str(emb)], "reads": "stdin", "emits": "stdout"},
        uses: {"run": ["python3", str(claude)], "reads": "stdin", "emits": emits},
    }}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return tmp_path, uses


def _corpus(tmp_path, uses, *, synthesize=True):
    asks = "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
    if synthesize:
        asks += (f"    synthesize:\n      uses: {uses}\n"
                 "      prompt: |\n        ${retrieved}\n        Pregunta: ${question}\n"
                 "    check: citations\n")
    corpus = tmp_path / "content" / "c"; corpus.mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\nask: ./ask.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\nfields: {}\npipeline: [{id: stamp, uses: engine.stamp}]\n")
    (corpus / "ask.yaml").write_text(
        "id: a\nversion: 1\nflow: ./flow.yaml\nindex:\n  uses: local.embed\n" + asks)
    return corpus


def _bundle(corpus, doc_id, chunks):
    pair = corpus / "corpus" / doc_id; pair.mkdir(parents=True)
    (pair / "chunks.jsonl").write_text("".join(json.dumps(c) + "\n" for c in chunks))
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "complete", "stages": [{"id": "x", "fields": {}}], "artifacts": {}})


def test_envelope_capability_records_model_tokens_cost_prompt_and_timing(tmp_path):
    machine, uses = _machine(tmp_path, envelope=True, answer="Sí [aaaaaaaaaaaa:r1].")
    corpus = _corpus(tmp_path, uses)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿qué?")
    prov = rec["provenance"]
    assert prov["model"] == "claude-opus-4-8"
    assert prov["usage"] == {"input_tokens": 1234, "output_tokens": 480,
                             "cache_read_input_tokens": 21434}
    assert prov["cost_usd"] == 0.046
    assert "grounding" in prov["prompt"].lower()        # the full prompt is captured
    assert "Pregunta: ¿qué?" in prov["prompt"]
    for key in ("retrieval_ms", "synthesis_ms", "total_ms"):
        assert isinstance(prov[key], int)


def test_plaintext_capability_records_timing_and_prompt_but_no_model(tmp_path):
    machine, uses = _machine(tmp_path, envelope=False, answer="Sí [aaaaaaaaaaaa:r1].")
    corpus = _corpus(tmp_path, uses)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿qué?")
    prov = rec["provenance"]
    assert "model" not in prov and "usage" not in prov   # no envelope → no model/usage
    assert "prompt" in prov                              # prompt is always available
    assert isinstance(prov["synthesis_ms"], int)


def test_find_records_retrieval_and_total_timing_only(tmp_path):
    machine, uses = _machine(tmp_path, envelope=True, answer="unused")
    corpus = _corpus(tmp_path, uses, synthesize=False)   # retrieve-only ask, no LLM
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿qué?")
    assert "answer" not in rec
    prov = rec["provenance"]
    assert set(prov) == {"retrieval_ms", "total_ms"}
    assert isinstance(prov["retrieval_ms"], int) and isinstance(prov["total_ms"], int)
