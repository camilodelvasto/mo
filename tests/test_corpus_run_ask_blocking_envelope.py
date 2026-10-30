# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The blocking path (mo corpus ask — the deploy smoke) on an envelope-shaped ask.

An ask that declares `attachments:` binds synthesize to an envelope reader; every
turn of it — image or not — is a multimodal envelope down `stream:`. The blocking
path must speak that wire shape too: the pre-flip deploy smoke runs `mo corpus ask`
against exposed_asks[0], and a vision ask there must answer, not refuse."""
import json
import textwrap
from pathlib import Path

import pytest
import yaml

from shapes.corpus.access import run_ask
from shapes.corpus.access.errors import AskError, HistoryError
from shapes.corpus.engine import sidecar


def _machine(tmp_path, dim=4):
    emb = tmp_path / "fake_embed.py"
    emb.write_text(textwrap.dedent(f"""
        import sys, json
        for l in sys.stdin:
            l=l.strip()
            if l:
                c=json.loads(l)
                print(json.dumps({{"ref":c["ref"],"vector":[0.1]*{dim},"dim":{dim},"model":"fake"}}))
    """).strip())
    # fake vision stream: refuses anything that is not a {system, messages} envelope,
    # then emits the NDJSON token/done contract of a stream: binding.
    vision = tmp_path / "fake_vision_stream.py"
    vision.write_text(textwrap.dedent("""
        import sys, json
        env = json.loads(sys.stdin.read())
        if not (isinstance(env.get("system"), str) and env.get("messages")):
            sys.exit("not an envelope")
        if env["messages"][-1]["role"] != "user":
            sys.exit("last message must be the user's")
        print(json.dumps({"event": "token", "text": "hola "}))
        print(json.dumps({"event": "token", "text": "mundo"}))
        print(json.dumps({"event": "done", "model": "fake-vision",
                          "usage": {"input_tokens": 1}, "cost_usd": 0.01}))
    """).strip())
    table = {"capabilities": {
        "local.embed": {"run": ["python3", str(emb)], "reads": "stdin", "emits": "stdout"},
        "api.claude-vision": {"stream": ["python3", str(vision)],
                              "reads": "envelope", "emits": "envelope"},
    }}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return tmp_path


def _corpus(tmp_path):
    corpus = tmp_path / "content" / "c"; corpus.mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\nask: ./ask.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\n"
        "fields: {visibility: {type: enum, values: [general, private], by: operator}}\n"
        "pipeline: [{id: stamp, uses: engine.stamp}]\n")
    (corpus / "ask.yaml").write_text(
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: vision\n"
        "    attachments: {accept: [image]}\n"
        "    retrieve: {mode: vector, k: 5}\n"
        "    synthesize:\n      uses: api.claude-vision\n      prompt: |\n"
        "        ${retrieved}\n        Pregunta: ${question}\n")
    return corpus


def _bundle(corpus, doc_id, chunks):
    pair = corpus / "corpus" / doc_id; pair.mkdir(parents=True)
    (pair / "chunks.jsonl").write_text("".join(json.dumps(c) + "\n" for c in chunks))
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "complete",
        "stages": [{"id": "x", "fields": {"visibility": "general"}}], "artifacts": {}})


def test_envelope_ask_answers_on_the_blocking_path(tmp_path):
    machine = _machine(tmp_path)
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "vision", "¿De qué trata este corpus?")
    assert rec["answer"] == "hola mundo"


def test_envelope_ask_blocking_provenance_carries_the_done_meta(tmp_path):
    machine = _machine(tmp_path)
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "vision", "¿qué?")
    assert rec["provenance"]["model"] == "fake-vision"
    assert rec["provenance"]["cost_usd"] == 0.01


def test_envelope_ask_blocking_names_malformed_history(tmp_path):
    # Parity with the streaming vision path: the envelope's message list demands
    # strict alternation, so the engine refuses a bad shape by name — never an
    # opaque provider rejection dressed as a synthesis failure.
    machine = _machine(tmp_path)
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    history = [{"role": "user", "content": "hola"}]   # ends on the user's turn
    with pytest.raises(HistoryError, match="user turn"):
        run_ask.run_ask(corpus, machine, "vision", "¿y ahora?", history=history)


def test_envelope_ask_blocking_provenance_prompt_is_the_full_text_sent(tmp_path):
    # _synthesize's contract: `prompt` is the full text sent to the model. On the
    # envelope path that is the system block (directive + retrieved passages) plus
    # every message's text — not just the last user turn.
    machine = _machine(tmp_path)
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    history = [{"role": "user", "content": "primera pregunta"},
               {"role": "assistant", "content": "primera respuesta"}]
    rec = run_ask.run_ask(corpus, machine, "vision", "¿qué dicen?", history=history)
    prompt = rec["provenance"]["prompt"]
    assert "educación" in prompt            # retrieved passage (rides the prompt body)
    assert "primera respuesta" in prompt    # history turn text
    assert "¿qué dicen?" in prompt          # the current question


def test_envelope_ask_blocking_refuses_history_that_carries_attachments(tmp_path):
    # Attachment verification (signature against the box secret) lives on the
    # streaming path; the blocking path never lets image bytes reach the envelope.
    machine = _machine(tmp_path)
    corpus = _corpus(tmp_path)
    _bundle(corpus, "aaaaaaaaaaaa", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    history = [{"role": "user", "content": "mira",
                "attachments": [{"data": "eA==", "signature": "0" * 64,
                                 "media_type": "image/webp"}]},
               {"role": "assistant", "content": "veo"}]
    with pytest.raises(AskError, match="streaming"):
        run_ask.run_ask(corpus, machine, "vision", "¿y ahora?", history=history)
