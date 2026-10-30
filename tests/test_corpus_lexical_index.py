# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""TDD suite: embedder-free lexical corpora.
Six tests proving the lexical path builds, serves, and is passport-verified
correctly — while the embedded path stays intact."""
import json
import textwrap
from pathlib import Path

import pytest
import yaml

from shapes.corpus.access import index, passport, run_ask
from shapes.corpus.access.errors import PassportError
from shapes.corpus.engine import sidecar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _machine_lexical(tmp_path, answer_template):
    """A machine with ONLY api.claude — no local.embed bound."""
    claude = tmp_path / "fake_claude.py"
    claude.write_text(textwrap.dedent(f"""
        import sys
        sys.stdin.read()
        sys.stdout.write({answer_template!r})
    """).strip())
    table = {"capabilities": {
        "api.claude": {"run": ["python3", str(claude)], "reads": "stdin", "emits": "stdout"},
    }}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return tmp_path


def _machine_embedded(tmp_path, answer_template, dim=4, model="fake"):
    """A machine with both local.embed and api.claude."""
    emb = tmp_path / "fake_embed.py"
    emb.write_text(textwrap.dedent(f"""
        import sys, json
        for l in sys.stdin:
            l = l.strip()
            if l:
                c = json.loads(l)
                print(json.dumps({{"ref": c["ref"], "vector": [0.1]*{dim},
                                   "dim": {dim}, "model": "{model}"}}))
    """).strip())
    claude = tmp_path / "fake_claude.py"
    claude.write_text(textwrap.dedent(f"""
        import sys
        sys.stdin.read()
        sys.stdout.write({answer_template!r})
    """).strip())
    table = {"capabilities": {
        "local.embed": {"run": ["python3", str(emb)], "reads": "stdin", "emits": "stdout"},
        "api.claude": {"run": ["python3", str(claude)], "reads": "stdin", "emits": "stdout"},
    }}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return tmp_path


def _corpus(tmp_path, ask_yaml):
    corpus = tmp_path / "content" / "c"
    corpus.mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\nask: ./ask.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\n"
        "fields: {visibility: {type: enum, values: [general, private], by: operator}}\n"
        "pipeline: [{id: stamp, uses: engine.stamp}]\n")
    (corpus / "ask.yaml").write_text(ask_yaml)
    return corpus


def _bundle(corpus, doc_id, chunks):
    pair = corpus / "corpus" / doc_id
    pair.mkdir(parents=True)
    (pair / "chunks.jsonl").write_text("".join(json.dumps(c) + "\n" for c in chunks))
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "complete",
        "stages": [{"id": "x", "fields": {"visibility": "general"}}],
        "artifacts": {}})


# ask.yaml for a lexical corpus — no `index` block
_LEXICAL_ASK = (
    "id: a\nversion: 1\nflow: ./flow.yaml\n"
    "asks:\n  - id: chat\n    retrieve: {mode: lexical, k: 5}\n"
    "    synthesize:\n      uses: api.claude\n"
    "      prompt: '${retrieved} ${question}'\n    check: citations\n"
)

# ask.yaml for an embedded corpus — declares index.uses
_EMBEDDED_ASK = (
    "id: a\nversion: 1\nflow: ./flow.yaml\n"
    "index:\n  uses: local.embed\n"
    "asks:\n  - id: chat\n    retrieve: {mode: vector, k: 5}\n"
    "    synthesize:\n      uses: api.claude\n"
    "      prompt: '${retrieved} ${question}'\n    check: citations\n"
)


# ---------------------------------------------------------------------------
# Test 1: lexical corpus builds with NO embedder binding
# ---------------------------------------------------------------------------

def test_lexical_corpus_builds_with_NO_embedder_binding(tmp_path):
    """End-to-end: no local.embed bound, corpus with no index.uses, must build and answer."""
    answer = "Según el informe [aaaaaaaaaaaa:r1] la educación es clave."
    machine = _machine_lexical(tmp_path, answer)
    corpus = _corpus(tmp_path, _LEXICAL_ASK)
    _bundle(corpus, "aaaaaaaaaaaa",
            [{"ref": "r1", "span": [0, 10], "text": "educación sexual básica"}])

    # If reconcile probed local.embed, it would raise CapabilityError (unbound).
    rec = run_ask.run_ask(corpus, machine, "chat", "educación")
    assert rec["answer"] == answer
    assert rec["passages"][0]["ref"] == "r1"

    # Passport must be lexical.
    stored = passport.read(corpus)
    assert stored is not None
    assert stored.get("retrieval") == "lexical"
    assert "dimension" not in stored


# ---------------------------------------------------------------------------
# Test 2: lexical index has no vec_chunks table
# ---------------------------------------------------------------------------

def test_lexical_index_has_no_vec_chunks_table(tmp_path):
    """After a lexical build, fts_chunks is present and vec_chunks is absent."""
    answer = "Según [aaaaaaaaaaaa:r1] sí."
    machine = _machine_lexical(tmp_path, answer)
    corpus = _corpus(tmp_path, _LEXICAL_ASK)
    _bundle(corpus, "aaaaaaaaaaaa",
            [{"ref": "r1", "span": [0, 5], "text": "hola mundo"}])

    run_ask.run_ask(corpus, machine, "chat", "hola")

    conn = index.open_index(corpus)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow', 'view')")}
    vtables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' OR type='shadow'")}
    all_names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()

    assert "fts_chunks" in all_names
    assert "chunks" in all_names
    # vec_chunks must not exist in any form
    assert not any("vec_chunks" in n for n in all_names)


# ---------------------------------------------------------------------------
# Test 3: lexical corpus serves repeated asks without passport error
# ---------------------------------------------------------------------------

def test_lexical_corpus_serves_repeated_asks_no_passport_error(tmp_path):
    """Second run_ask must not raise — verify skips the probe for a lexical corpus."""
    answer = "Según [aaaaaaaaaaaa:r1] sí."
    machine = _machine_lexical(tmp_path, answer)
    corpus = _corpus(tmp_path, _LEXICAL_ASK)
    _bundle(corpus, "aaaaaaaaaaaa",
            [{"ref": "r1", "span": [0, 5], "text": "educación"}])

    run_ask.run_ask(corpus, machine, "chat", "educación")  # builds index
    # Second call — if verify probed local.embed this would raise CapabilityError.
    rec2 = run_ask.run_ask(corpus, machine, "chat", "educación")
    assert rec2["answer"] == answer


# ---------------------------------------------------------------------------
# Test 4: embedded corpus still embeds every chunk (regression)
# ---------------------------------------------------------------------------

def test_embedded_corpus_still_embeds_every_chunk(tmp_path):
    """An embedded corpus must still produce vec_chunks rows for every chunk."""
    answer = "Según [aaaaaaaaaaaa:r1] sí."
    machine = _machine_embedded(tmp_path, answer, dim=4)
    corpus = _corpus(tmp_path, _EMBEDDED_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", [
        {"ref": "r1", "span": [0, 5], "text": "chunk one"},
        {"ref": "r2", "span": [5, 10], "text": "chunk two"},
    ])

    rec = run_ask.run_ask(corpus, machine, "chat", "chunk")
    assert rec["answer"] == answer

    conn = index.open_index(corpus)
    vec_count = conn.execute("SELECT count(*) FROM vec_chunks").fetchone()[0]
    conn.close()
    assert vec_count == 2


# ---------------------------------------------------------------------------
# Test 5: embedded corpus drift-catches on model change (regression)
# ---------------------------------------------------------------------------

def test_embedded_corpus_drift_catches_on_model_change(tmp_path):
    """After building embedded with model-A, switching to model-B must raise PassportError."""
    answer = "Según [aaaaaaaaaaaa:r1] sí."
    machine_a = _machine_embedded(tmp_path, answer, dim=4, model="model-A")
    corpus = _corpus(tmp_path, _EMBEDDED_ASK)
    _bundle(corpus, "aaaaaaaaaaaa",
            [{"ref": "r1", "span": [0, 5], "text": "texto"}])

    run_ask.run_ask(corpus, machine_a, "chat", "texto")  # builds with model-A

    # Now swap to model-B — same dim, different model.
    # We create a new machine that overwrites capabilities.yaml in the same tmp_path.
    emb_b = tmp_path / "fake_embed_b.py"
    emb_b.write_text(textwrap.dedent("""
        import sys, json
        for l in sys.stdin:
            l = l.strip()
            if l:
                c = json.loads(l)
                print(json.dumps({"ref": c["ref"], "vector": [0.1]*4,
                                   "dim": 4, "model": "model-B"}))
    """).strip())
    table = yaml.safe_load((tmp_path / "capabilities.yaml").read_text())
    table["capabilities"]["local.embed"]["run"] = ["python3", str(emb_b)]
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))

    with pytest.raises(PassportError, match="model"):
        run_ask.run_ask(corpus, machine_a, "chat", "texto")


# ---------------------------------------------------------------------------
# Test 6: passport kind mismatch raises
# ---------------------------------------------------------------------------

def test_passport_kind_mismatch_raises(tmp_path):
    """Build lexical, then re-declare an embedder → PassportError naming the mismatch."""
    answer = "Según [aaaaaaaaaaaa:r1] sí."
    machine = _machine_lexical(tmp_path, answer)
    corpus = _corpus(tmp_path, _LEXICAL_ASK)
    _bundle(corpus, "aaaaaaaaaaaa",
            [{"ref": "r1", "span": [0, 5], "text": "texto"}])

    run_ask.run_ask(corpus, machine, "chat", "texto")  # builds lexical index

    # Rewrite ask.yaml to declare an embedder (now embedded mode).
    # Also add the local.embed capability to the machine.
    emb = tmp_path / "fake_embed_km.py"
    emb.write_text(textwrap.dedent("""
        import sys, json
        for l in sys.stdin:
            l = l.strip()
            if l:
                c = json.loads(l)
                print(json.dumps({"ref": c["ref"], "vector": [0.1]*4,
                                   "dim": 4, "model": "fake"}))
    """).strip())
    table = yaml.safe_load((tmp_path / "capabilities.yaml").read_text())
    table["capabilities"]["local.embed"] = {
        "run": ["python3", str(emb)], "reads": "stdin", "emits": "stdout"}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))

    # Rewrite ask.yaml with index.uses to switch to embedded mode.
    (corpus / "ask.yaml").write_text(_EMBEDDED_ASK)

    with pytest.raises(PassportError, match="kind mismatch"):
        run_ask.run_ask(corpus, machine, "chat", "texto")


# ---------------------------------------------------------------------------
# Test 7: empty index.uses in ask.yaml raises AskError
# ---------------------------------------------------------------------------

def test_empty_index_uses_raises_ask_error(tmp_path):
    """ask.yaml with index: {uses: ''} must raise AskError naming 'empty', not silently treat as lexical."""
    from shapes.corpus.access.askfile import declared_embedder
    from shapes.corpus.access.errors import AskError

    ask_yaml_empty_uses = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: \"\"\n"
        "asks:\n  - id: chat\n    retrieve: {mode: lexical, k: 5}\n"
        "    synthesize:\n      uses: api.claude\n"
        "      prompt: '${retrieved} ${question}'\n    check: citations\n"
    )
    corpus = _corpus(tmp_path, ask_yaml_empty_uses)
    with pytest.raises(AskError, match="empty"):
        declared_embedder(corpus)


# ---------------------------------------------------------------------------
# Test 8: reverse kind mismatch — embedded passport, lexical declaration raises
# ---------------------------------------------------------------------------

def test_passport_reverse_kind_mismatch_raises(tmp_path):
    """Build embedded, then remove index block (now lexical) → PassportError naming kind mismatch."""
    answer = "Según [aaaaaaaaaaaa:r1] sí."
    machine = _machine_embedded(tmp_path, answer, dim=4)
    corpus = _corpus(tmp_path, _EMBEDDED_ASK)
    _bundle(corpus, "aaaaaaaaaaaa",
            [{"ref": "r1", "span": [0, 5], "text": "texto"}])

    run_ask.run_ask(corpus, machine, "chat", "texto")  # builds embedded index

    # Rewrite ask.yaml to remove the index block (now lexical declaration).
    lexical_ask = _LEXICAL_ASK
    (corpus / "ask.yaml").write_text(lexical_ask)

    with pytest.raises(PassportError, match="kind mismatch"):
        run_ask.run_ask(corpus, machine, "chat", "texto")
