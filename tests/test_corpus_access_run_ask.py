import json
import textwrap
from pathlib import Path

import pytest
import yaml

from shapes.corpus.access import run_ask
from shapes.corpus.access.errors import AskError, CitationError, SynthesisError
from shapes.corpus.engine import sidecar


def _machine(tmp_path, answer_template, dim=4):
    emb = tmp_path / "fake_embed.py"
    emb.write_text(textwrap.dedent(f"""
        import sys, json
        for l in sys.stdin:
            l=l.strip()
            if l:
                c=json.loads(l)
                print(json.dumps({{"ref":c["ref"],"vector":[0.1]*{dim},"dim":{dim},"model":"fake"}}))
    """).strip())
    # fake claude: reads prompt on stdin, writes a fixed answer (template) on stdout
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
    corpus = tmp_path / "content" / "c"; corpus.mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\nask: ./ask.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\n"
        "fields: {visibility: {type: enum, values: [general, private], by: operator}}\n"
        "pipeline: [{id: stamp, uses: engine.stamp}]\n")
    (corpus / "ask.yaml").write_text(ask_yaml)
    return corpus


def _bundle(corpus, doc_id, visibility, chunks):
    pair = corpus / "corpus" / doc_id; pair.mkdir(parents=True)
    (pair / "chunks.jsonl").write_text("".join(json.dumps(c) + "\n" for c in chunks))
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "complete",
        "stages": [{"id": "x", "fields": {"visibility": visibility}}], "artifacts": {}})


FIND_ASK = "id: a\nversion: 1\nflow: ./flow.yaml\nindex:\n  uses: local.embed\nasks:\n  - id: find\n    retrieve: {mode: vector, k: 5}\n"


def test_find_ask_returns_passages_no_llm(tmp_path):
    machine = _machine(tmp_path, "unused")
    corpus = _corpus(tmp_path, FIND_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general",
            [{"ref": "r1", "span": [0, 4], "text": "educación sexual"}])
    rec = run_ask.run_ask(corpus, machine, "find", "educación")
    assert rec["passages"] and rec["passages"][0]["ref"] == "r1"
    assert "answer" not in rec


def test_answer_ask_synthesizes_and_passes_citation_check(tmp_path):
    answer = "Según el informe [aaaaaaaaaaaa:r1] la educación es clave."
    machine = _machine(tmp_path, answer)
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
        "    where: visibility == general\n    prime: grounded\n"
        "    synthesize:\n      uses: api.claude\n      prompt: |\n"
        "        ${retrieved}\n        Pregunta: ${question}\n    check: citations\n"
        "profiles:\n  grounded:\n    system: Eres preciso.\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general",
            [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿qué dicen?")
    assert rec["answer"] == answer
    assert rec["passages"][0]["ref"] == "r1"


def test_fabricated_citation_throws(tmp_path):
    answer = "Inventado [aaaaaaaaaaaa:deadbeef] sin fuente."
    machine = _machine(tmp_path, answer)
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
        "    synthesize:\n      uses: api.claude\n      prompt: '${retrieved} ${question}'\n"
        "    check: citations\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general",
            [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    with pytest.raises(CitationError, match="deadbeef"):
        run_ask.run_ask(corpus, machine, "answer", "¿qué?")


def test_grounding_directive_does_not_force_citations(tmp_path):
    # the default directive controls source-adherence only; it must NOT hardcode a
    # citation instruction — citing is the prompt author's choice, not the engine's.
    d = run_ask._grounding_directive(0.5)
    assert "[doc:chunk]" not in d
    assert "Cite every claim" not in d
    assert "grounding level" in d.lower()          # the adherence knob is still there


def test_today_placeholder_resolves_to_current_date(tmp_path, monkeypatch):
    # ${today} is an available placeholder: the prompt author feeds the current date so
    # the model doesn't treat 2026 corpus events as "future". Prompt-controlled — the
    # engine resolves it only where the author places it, never injected on its own.
    monkeypatch.setattr(run_ask, "_today", lambda: "2026-07-03")
    machine = _machine(tmp_path, "ok")
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: none}\n    grounding: 0.0\n"
        "    synthesize:\n      uses: api.claude\n      prompt: 'Hoy es ${today}. ${question}'\n")
    corpus = _corpus(tmp_path, ask_yaml)
    rec = run_ask.run_ask(corpus, machine, "answer", "¿q?")
    assert "Hoy es 2026-07-03" in rec["provenance"]["prompt"]
    assert "${today}" not in rec["provenance"]["prompt"]


def test_render_sources_dedupes_by_document():
    # ${sources} is a per-DOCUMENT list (one line per unique doc, its name), not
    # per-chunk — two chunks of one document collapse to a single source line.
    passages = [
        {"doc_id": "aaaaaaaaaaaa", "ref": "r1", "name": "Doc A"},
        {"doc_id": "aaaaaaaaaaaa", "ref": "r2", "name": "Doc A"},
        {"doc_id": "bbbbbbbbbbbb", "ref": "r1", "name": "Doc B"},
    ]
    assert run_ask._render_sources(passages) == "Doc A\nDoc B"


def test_sources_placeholder_is_resolved_when_present(tmp_path):
    # ${sources} is an available placeholder the prompt author positions; run_ask
    # resolves it (no literal ${sources} survives) under the author's own heading.
    machine = _machine(tmp_path, "una respuesta")
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
        "    synthesize:\n      uses: api.claude\n      prompt: |\n"
        "        ${retrieved}\n        Fuentes:\n        ${sources}\n        Pregunta: ${question}\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "uno"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿q?")
    prompt = rec["provenance"]["prompt"]
    assert "${sources}" not in prompt        # the placeholder was resolved
    assert "Fuentes:" in prompt              # positioned by the author


def test_no_sources_placeholder_means_no_source_list(tmp_path):
    # without ${sources} in the prompt, nothing about sources is injected.
    answer = "una respuesta"
    machine = _machine(tmp_path, answer)
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
        "    synthesize:\n      uses: api.claude\n      prompt: 'Solo: ${question}'\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "uno"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿q?")
    assert "Fuentes" not in rec["provenance"]["prompt"]


def test_synthesize_auto_injects_passages_without_retrieved_slot(tmp_path):
    # declarative grounding: declaring retrieve grounds the ask. When the prompt has no
    # ${retrieved} token, the engine wires the retrieved passages into the model context
    # automatically — no author plumbing, no silent drop.
    answer = "Según el informe [aaaaaaaaaaaa:r1] la educación es clave."
    machine = _machine(tmp_path, answer)
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
        "    synthesize:\n      uses: api.claude\n      prompt: 'Pregunta: ${question}'\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general",
            [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "educación")
    assert rec["answer"] == answer
    # the retrieved passage was injected into the model context, labelled by source
    # NAME (doc_id here, since the test bundle sets no source_name) — never dropped
    assert "[aaaaaaaaaaaa]" in rec["provenance"]["prompt"]


def test_synthesize_without_slot_and_no_passages_is_fine(tmp_path):
    # the advisor shape: a no-retrieval advisor (mode none / grounding 0.0) has no
    # passages, so a prompt without ${retrieved} is correct, not a dropped-source bug.
    machine = _machine(tmp_path, "una estrategia")
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: advisor\n    retrieve: {mode: none}\n    grounding: 0.0\n"
        "    synthesize:\n      uses: api.claude\n      prompt: 'Pregunta: ${question}'\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "advisor", "¿cómo avanzo mi causa?")
    assert rec["answer"] == "una estrategia"
    assert rec["passages"] == []


def test_caller_where_narrows_scope(tmp_path):
    machine = _machine(tmp_path, "unused")
    corpus = _corpus(tmp_path, FIND_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    _bundle(corpus, "bbbbbbbbbbbb", "private", [{"ref": "r2", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "find", "x", where="visibility == private")
    assert {p["doc_id"] for p in rec["passages"]} == {"bbbbbbbbbbbb"}


def test_check_citations_ignores_incidental_brackets():
    passages = [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "x"}]
    # a timestamp and a non-citation bracket must NOT be treated as fabricated citations
    run_ask._check_citations("La reunión fue a las [10:30] y [ver: nota 3].", passages)


def test_check_citations_passes_wellformed_real_marker():
    passages = [{"doc_id": "d047abd3e493", "ref": "c2525c3ae", "text": "x"}]
    run_ask._check_citations("Según [d047abd3e493:c2525c3ae] esto es así.", passages)


def test_check_citations_raises_on_wellformed_fabrication():
    passages = [{"doc_id": "d047abd3e493", "ref": "c2525c3ae", "text": "x"}]
    with pytest.raises(CitationError):
        run_ask._check_citations("Inventado [ffffffffffff:abc123] sin fuente.", passages)


def test_check_citations_validates_present_nonhex_ref():
    # a non-hex ref that IS in the retrieval set must pass (gate is ref-alphabet-agnostic)
    passages = [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "x"}]
    run_ask._check_citations("ver [aaaaaaaaaaaa:r1] aquí", passages)


def test_check_citations_catches_fabricated_nonhex_ref():
    # a non-hex ref NOT in the set must raise — proving non-hex refs are NOT silently skipped
    passages = [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "x"}]
    with pytest.raises(CitationError):
        run_ask._check_citations("ver [aaaaaaaaaaaa:r9] aquí", passages)


def test_attach_names_labels_passages_with_source_name():
    passages = [{"doc_id": "abc123abc123", "ref": "r1"},
                {"doc_id": "def456def456", "ref": "r2"}]
    projections = {"abc123abc123": {"source_name": "estudio-esi.md"}}  # def456 absent
    run_ask._attach_names(passages, projections)
    assert passages[0]["name"] == "estudio-esi.md"
    assert passages[1]["name"] == "def456def456"     # no projection → falls back to doc_id


def _machine_decompose(tmp_path, answer_template, dim=4):
    """_machine plus an `api.decompose` capability that echoes its stdin — so a test
    can read back exactly what the decompose stage was handed."""
    machine = _machine(tmp_path, answer_template, dim=dim)
    table = yaml.safe_load((machine / "capabilities.yaml").read_text())
    echo = tmp_path / "fake_decompose.py"
    echo.write_text("import sys; sys.stdout.write(sys.stdin.read())")
    table["capabilities"]["api.decompose"] = {
        "run": ["python3", str(echo)], "reads": "stdin", "emits": "stdout"}
    (machine / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return machine


DECOMPOSE_ASK = (
    "id: a\nversion: 1\nflow: ./flow.yaml\n"
    "index:\n  uses: local.embed\n"
    "asks:\n  - id: converse\n"
    "    decompose:\n      uses: api.decompose\n"
    "      prompt: |\n        ${history}\n        FU: ${question}\n"
    "    retrieve: {mode: vector, k: 5}\n"
    "    synthesize:\n      uses: api.claude\n      prompt: '${retrieved} ${question}'\n"
    "    check: citations\n")


def test_decompose_resolves_history_and_question(tmp_path):
    # the echo capability returns the resolved prompt; its lines become the planned
    # queries, so ${history} and ${question} must be substituted before the call.
    answer = "Según [aaaaaaaaaaaa:r1] sí."
    machine = _machine_decompose(tmp_path, answer)
    corpus = _corpus(tmp_path, DECOMPOSE_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    history = [{"role": "user", "content": "tema vivienda"},
               {"role": "assistant", "content": "ok"}]
    rec = run_ask.run_ask(corpus, machine, "converse", "¿y eso?", history=history)
    assert any("tema vivienda" in q for q in rec["queries"])   # ${history} resolved
    assert any("FU: ¿y eso?" in q for q in rec["queries"])       # ${question} resolved
    assert rec["answer"] == answer


def test_decompose_runs_on_empty_history(tmp_path):
    # the turn-1 fix: with decompose declared, planning runs even on the first message
    # (empty history), so a compound first turn is still decomposed for retrieval.
    answer = "Según [aaaaaaaaaaaa:r1] sí."
    machine = _machine_decompose(tmp_path, answer)
    corpus = _corpus(tmp_path, DECOMPOSE_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "converse", "¿y eso?", history=[])
    assert "queries" in rec and rec["queries"]                   # planned, not skipped


def test_ask_without_decompose_uses_raw_question(tmp_path):
    answer = "Según [aaaaaaaaaaaa:r1] sí."
    machine = _machine(tmp_path, answer)
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
        "    synthesize:\n      uses: api.claude\n      prompt: '${retrieved} ${question}'\n"
        "    check: citations\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿qué?",
                          history=[{"role": "user", "content": "hola"}])
    assert rec["answer"] == answer
    assert "queries" not in rec                                  # no decompose → raw single query


def test_decompose_empty_output_raises_synthesis_error(tmp_path):
    # an empty plan is a failed decompose, never a silent fall back to the raw question.
    machine = _machine(tmp_path, "unused")
    table = yaml.safe_load((machine / "capabilities.yaml").read_text())
    empty = tmp_path / "fake_empty.py"
    empty.write_text("import sys; sys.stdin.read()")            # reads, writes nothing
    table["capabilities"]["api.decompose"] = {
        "run": ["python3", str(empty)], "reads": "stdin", "emits": "stdout"}
    (machine / "capabilities.yaml").write_text(yaml.safe_dump(table))
    corpus = _corpus(tmp_path, DECOMPOSE_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    with pytest.raises(SynthesisError):
        run_ask.run_ask(corpus, machine, "converse", "¿y?", history=[])


def test_decompose_envelope_capability_splits_answer_lines(tmp_path):
    # an envelope-emitting capability (like api.claude-json): _plan_queries takes the
    # `answer` field, then splits it into one query per line.
    answer = "Según [aaaaaaaaaaaa:r1] sí."
    machine = _machine(tmp_path, answer)
    table = yaml.safe_load((machine / "capabilities.yaml").read_text())
    envdec = tmp_path / "fake_envdecompose.py"
    envdec.write_text("import sys,json; sys.stdin.read(); "
                      "sys.stdout.write(json.dumps({'answer':'consulta uno\\nconsulta dos','model':'fake'}))")
    table["capabilities"]["api.decompose-json"] = {
        "run": ["python3", str(envdec)], "reads": "stdin", "emits": "envelope"}
    (machine / "capabilities.yaml").write_text(yaml.safe_dump(table))
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: converse\n"
        "    decompose:\n      uses: api.decompose-json\n      prompt: '${history} ${question}'\n"
        "    retrieve: {mode: vector, k: 5}\n"
        "    synthesize:\n      uses: api.claude\n      prompt: '${retrieved} ${question}'\n"
        "    check: citations\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "converse", "¿y?", history=[])
    assert rec["queries"] == ["consulta uno", "consulta dos"]


def test_decompose_multi_query_changes_retrieval(tmp_path):
    # the mechanism: two docs, each hit by a different planned query lexically; the raw
    # question ("gamma") hits neither. Decompose fans out → both docs retrieved.
    machine = _machine(tmp_path, "unused")
    table = yaml.safe_load((machine / "capabilities.yaml").read_text())
    fixed = tmp_path / "fake_fixed.py"
    fixed.write_text("import sys; sys.stdin.read(); sys.stdout.write('alfa\\nbeta')")
    table["capabilities"]["api.decompose"] = {
        "run": ["python3", str(fixed)], "reads": "stdin", "emits": "stdout"}
    (machine / "capabilities.yaml").write_text(yaml.safe_dump(table))
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: converse\n"
        "    decompose:\n      uses: api.decompose\n      prompt: '${question}'\n"
        "    retrieve: {mode: lexical, k: 5}\n")          # retrieve-only: no LLM synth needed
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "alfa uno"}])
    _bundle(corpus, "bbbbbbbbbbbb", "general", [{"ref": "r2", "span": [0, 4], "text": "beta dos"}])
    rec = run_ask.run_ask(corpus, machine, "converse", "gamma", history=[])
    assert rec["queries"] == ["alfa", "beta"]
    assert {p["doc_id"] for p in rec["passages"]} == {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}


def test_synthesize_receives_history(tmp_path):
    # ${history} in a synthesize prompt resolves to the conversation turns, so a
    # strategist that must count rounds (e.g. "answer after 2-3 questions") can
    # see them. An echo capability writes the full prompt back as the answer.
    machine = _machine(tmp_path, "unused")
    echo = tmp_path / "fake_echo.py"
    echo.write_text("import sys; sys.stdout.write(sys.stdin.read())")
    table = yaml.safe_load((machine / "capabilities.yaml").read_text())
    table["capabilities"]["api.echo"] = {
        "run": ["python3", str(echo)], "reads": "stdin", "emits": "stdout"}
    (machine / "capabilities.yaml").write_text(yaml.safe_dump(table))
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: chat\n    retrieve: {mode: none}\n    grounding: 0.0\n"
        "    synthesize:\n      uses: api.echo\n      prompt: |\n"
        "        Conversacion:\n        ${history}\n        Pregunta: ${question}\n")
    corpus = _corpus(tmp_path, ask_yaml)
    history = [{"role": "user", "content": "trabajo en Colombia"},
               {"role": "assistant", "content": "entendido"}]
    rec = run_ask.run_ask(corpus, machine, "chat", "y ahora?", history=history)
    assert "user: trabajo en Colombia" in rec["answer"]   # ${history} resolved
    assert "assistant: entendido" in rec["answer"]


def test_synthesize_history_empty_when_no_turns(tmp_path):
    # No history → ${history} resolves to empty, never the literal token.
    machine = _machine(tmp_path, "unused")
    echo = tmp_path / "fake_echo.py"
    echo.write_text("import sys; sys.stdout.write(sys.stdin.read())")
    table = yaml.safe_load((machine / "capabilities.yaml").read_text())
    table["capabilities"]["api.echo"] = {
        "run": ["python3", str(echo)], "reads": "stdin", "emits": "stdout"}
    (machine / "capabilities.yaml").write_text(yaml.safe_dump(table))
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: chat\n    retrieve: {mode: none}\n    grounding: 0.0\n"
        "    synthesize:\n      uses: api.echo\n      prompt: 'H:${history}:Q:${question}'\n")
    corpus = _corpus(tmp_path, ask_yaml)
    rec = run_ask.run_ask(corpus, machine, "chat", "hola", history=[])
    assert "${history}" not in rec["answer"]
    assert "H::Q:hola" in rec["answer"]


_GROUNDED_ASK = (
    "id: a\nversion: 1\nflow: ./flow.yaml\n"
    "index:\n  uses: local.embed\n"
    "asks:\n  - id: answer\n    grounding: 0.4\n    retrieve: {mode: vector, k: 5}\n"
    "    synthesize:\n      uses: api.claude\n      prompt: '${retrieved} ${question}'\n"
    "    check: citations\n")


def test_ask_declared_grounding_default_used(tmp_path):
    # the web sends no grounding; the ask's own `grounding: 0.4` must govern.
    machine = _machine(tmp_path, "Según [aaaaaaaaaaaa:r1] sí.")
    corpus = _corpus(tmp_path, _GROUNDED_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿q?")          # no grounding passed
    assert "Source-grounding level: 0.4" in rec["provenance"]["prompt"]


def test_caller_grounding_overrides_ask_default(tmp_path):
    machine = _machine(tmp_path, "Según [aaaaaaaaaaaa:r1] sí.")
    corpus = _corpus(tmp_path, _GROUNDED_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿q?", grounding=0.9)
    assert "Source-grounding level: 0.9" in rec["provenance"]["prompt"]


def test_grounding_band_low_leans_on_own_knowledge(tmp_path):
    # 0.4 must read as "lean on your knowledge, passages support" — not "weight accordingly".
    machine = _machine(tmp_path, "Según [aaaaaaaaaaaa:r1] sí.")
    corpus = _corpus(tmp_path, _GROUNDED_ASK)                        # grounding: 0.4
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿q?")
    assert "substantially on your own knowledge" in rec["provenance"]["prompt"]


def test_grounding_band_high_only_passages(tmp_path):
    machine = _machine(tmp_path, "Según [aaaaaaaaaaaa:r1] sí.")
    corpus = _corpus(tmp_path, _GROUNDED_ASK.replace("grounding: 0.4", "grounding: 1.0"))
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿q?")
    assert "ONLY the provided passages" in rec["provenance"]["prompt"]


def test_invalid_ask_grounding_throws(tmp_path):
    machine = _machine(tmp_path, "x")
    bad = _GROUNDED_ASK.replace("grounding: 0.4", "grounding: 2.0")
    corpus = _corpus(tmp_path, bad)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    with pytest.raises(AskError, match="grounding"):
        run_ask.run_ask(corpus, machine, "answer", "¿q?")


# --- decoupled title: synthesis is plain prose; the title is a separate step ---

def _machine_titled(tmp_path, prose, title, dim=4):
    """Like _machine, but the fake claude returns `title` for the title step
    (detected by the injected _TITLE_PROMPT marker) and `prose` for synthesis."""
    emb = tmp_path / "fake_embed.py"
    emb.write_text(textwrap.dedent(f"""
        import sys, json
        for l in sys.stdin:
            l=l.strip()
            if l:
                c=json.loads(l)
                print(json.dumps({{"ref":c["ref"],"vector":[0.1]*{dim},"dim":{dim},"model":"fake"}}))
    """).strip())
    claude = tmp_path / "fake_claude.py"
    claude.write_text(textwrap.dedent(f"""
        import sys
        data = sys.stdin.read()
        sys.stdout.write({title!r} if "naming this conversation" in data else {prose!r})
    """).strip())
    table = {"capabilities": {
        "local.embed": {"run": ["python3", str(emb)], "reads": "stdin", "emits": "stdout"},
        "api.claude": {"run": ["python3", str(claude)], "reads": "stdin", "emits": "stdout"},
    }}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return tmp_path


_TITLED_ASK = (
    "id: a\nversion: 1\nflow: ./flow.yaml\n"
    "index:\n  uses: local.embed\n"
    "asks:\n  - id: converse\n    retrieve: {mode: vector, k: 5}\n"
    "    prime: grounded\n"
    "    synthesize:\n      uses: api.claude\n      titled: true\n"
    "      prompt: '${retrieved} ${question}'\n"
    "profiles:\n  grounded:\n    system: Eres preciso.\n")


def test_titled_first_turn_sets_prose_answer_and_title(tmp_path):
    machine = _machine_titled(tmp_path, prose="La educación es clave.", title="Educación sexual")
    corpus = _corpus(tmp_path, _TITLED_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "converse", "¿qué dicen?")
    assert rec["answer"] == "La educación es clave."   # plain prose, not a JSON wrapper
    assert rec["title"] == "Educación sexual"          # from the separate title step


def test_titled_synthesis_prompt_has_no_title_instruction(tmp_path):
    machine = _machine_titled(tmp_path, prose="Sí.", title="Tema")
    corpus = _corpus(tmp_path, _TITLED_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "converse", "¿q?")
    # the title instruction is NOT in the synthesis prompt anymore — it is decoupled
    assert "naming this conversation" not in rec["provenance"]["prompt"]


def test_titled_later_turn_skips_title(tmp_path):
    machine = _machine_titled(tmp_path, prose="Sí.", title="Tema")
    corpus = _corpus(tmp_path, _TITLED_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    rec = run_ask.run_ask(corpus, machine, "converse", "¿y ahora?",
                          history=[{"role": "user", "content": "hola"}])
    assert "title" not in rec                           # a conversation is named once


def test_titled_title_failure_degrades_to_question(tmp_path):
    # a title capability that exits non-zero on the title call → label = trimmed question
    emb = tmp_path / "fake_embed.py"
    emb.write_text("import sys,json\n"
                   "for l in sys.stdin:\n"
                   "    l=l.strip()\n"
                   "    if l:\n"
                   "        c=json.loads(l); print(json.dumps({'ref':c['ref'],'vector':[0.1]*4,'dim':4,'model':'f'}))")
    claude = tmp_path / "fake_claude.py"
    claude.write_text("import sys\n"
                      "data=sys.stdin.read()\n"
                      "sys.exit(1) if 'naming this conversation' in data else sys.stdout.write('La respuesta.')")
    table = {"capabilities": {
        "local.embed": {"run": ["python3", str(emb)], "reads": "stdin", "emits": "stdout"},
        "api.claude": {"run": ["python3", str(claude)], "reads": "stdin", "emits": "stdout"},
    }}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    corpus = _corpus(tmp_path, _TITLED_ASK)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    q = "necesito preparar un plan de viaje para visitar varios museos"
    rec = run_ask.run_ask(corpus, tmp_path, "converse", q)   # machine_root = tmp_path
    assert rec["answer"] == "La respuesta."             # the answer survives
    assert rec["title"] == run_ask._trim_question(q)    # label degraded to the question baseline


def test_non_titled_ask_has_no_title_and_answer_is_prose(tmp_path):
    # answer/explorar use api.claude-json too but are NOT titled — unaffected.
    answer = "Según el informe [aaaaaaaaaaaa:r1] la educación es clave."
    machine = _machine(tmp_path, answer)
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
        "    synthesize:\n      uses: api.claude\n      prompt: '${retrieved} ${question}'\n"
        "    check: citations\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general",
            [{"ref": "r1", "span": [0, 4], "text": "educación"}])
    rec = run_ask.run_ask(corpus, machine, "answer", "¿qué?")
    assert rec["answer"] == answer
    assert "title" not in rec
    assert '"title"' not in rec["provenance"]["prompt"]   # no injection for non-titled


def test_synthesis_spawn_failure_raises_synthesis_error(tmp_path):
    machine = _machine(tmp_path, "unused")
    table = yaml.safe_load((machine / "capabilities.yaml").read_text())
    boom = tmp_path / "fake_boom.py"
    boom.write_text("import sys; sys.stdin.read(); sys.exit(1)")
    table["capabilities"]["api.claude"] = {
        "run": ["python3", str(boom)], "reads": "stdin", "emits": "stdout"}
    (machine / "capabilities.yaml").write_text(yaml.safe_dump(table))
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: vector, k: 5}\n"
        "    synthesize:\n      uses: api.claude\n      prompt: '${retrieved} ${question}'\n"
        "    check: citations\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [{"ref": "r1", "span": [0, 4], "text": "x"}])
    with pytest.raises(SynthesisError):
        run_ask.run_ask(corpus, machine, "answer", "¿qué?")


# --- decoupled title: baseline trim + the bounded title step ---

def _title_machine(tmp_path, label, *, emits="stdout", rc=0, dim=4):
    """capabilities.yaml whose api.claude fake returns `label` (rc/emits configurable)."""
    claude = tmp_path / "fake_title.py"
    if emits == "envelope":
        body = f'import sys,json; sys.stdin.read(); sys.stdout.write(json.dumps({{"answer": {label!r}}})); sys.exit({rc})'
    else:
        body = f'import sys; sys.stdin.read(); sys.stdout.write({label!r}); sys.exit({rc})'
    claude.write_text(body)
    table = {"capabilities": {
        "api.claude": {"run": ["python3", str(claude)], "reads": "stdin", "emits": emits},
    }}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump(table))
    return tmp_path


_TITLE_ASK = {"synthesize": {"uses": "api.claude"}}


def test_trim_question_short_is_verbatim():
    assert run_ask._trim_question("quién ganó el torneo") == "quién ganó el torneo"


def test_trim_question_long_takes_six_words_with_ellipsis():
    q = "necesito preparar un plan de viaje para visitar varios museos"
    assert run_ask._trim_question(q) == "necesito preparar un plan de viaje…"


def test_title_returns_polished_label(tmp_path):
    machine = _title_machine(tmp_path, "Torneo de Ajedrez 2026")
    assert run_ask._title(_TITLE_ASK, "¿quién ganó?", machine) == "Torneo de Ajedrez 2026"


def test_title_strips_surrounding_quotes(tmp_path):
    machine = _title_machine(tmp_path, '"Torneo de Ajedrez"')
    assert run_ask._title(_TITLE_ASK, "¿quién ganó?", machine) == "Torneo de Ajedrez"


def test_title_reads_envelope_answer(tmp_path):
    machine = _title_machine(tmp_path, "Receta de pan", emits="envelope")
    assert run_ask._title(_TITLE_ASK, "¿q?", machine) == "Receta de pan"


def test_title_degrades_to_trim_on_nonzero_exit(tmp_path):
    machine = _title_machine(tmp_path, "ignored", rc=1)
    q = "necesito preparar un plan de viaje para visitar varios museos"
    assert run_ask._title(_TITLE_ASK, q, machine) == run_ask._trim_question(q)


def test_title_degrades_to_trim_on_empty_output(tmp_path):
    machine = _title_machine(tmp_path, "   ")
    assert run_ask._title(_TITLE_ASK, "quién ganó", machine) == "quién ganó"


def test_title_raises_on_non_stdin_reads(tmp_path):
    # A binding that reads neither a prompt (stdin) nor an envelope is a binding
    # error — named, at the capability level, not an ask error.
    claude = tmp_path / "fake.py"
    claude.write_text("import sys; sys.exit(0)")
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump({"capabilities": {
        "api.claude": {"run": ["python3", str(claude)], "reads": "file"},
    }}))
    from shapes.corpus.engine.errors import CapabilityError
    with pytest.raises(CapabilityError, match="reads: stdin"):
        run_ask._title(_TITLE_ASK, "¿q?", tmp_path)


def test_trim_question_exactly_six_words_verbatim():
    assert run_ask._trim_question("uno dos tres cuatro cinco seis") == "uno dos tres cuatro cinco seis"


def test_title_degrades_when_envelope_is_not_a_dict(tmp_path):
    # an envelope capability whose JSON is a non-dict (a list) must degrade, not raise
    claude = tmp_path / "fake.py"
    claude.write_text('import sys; sys.stdin.read(); sys.stdout.write("[1, 2, 3]")')
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump({"capabilities": {
        "api.claude": {"run": ["python3", str(claude)], "reads": "stdin", "emits": "envelope"},
    }}))
    q = "necesito preparar un plan de viaje para visitar varios museos"
    assert run_ask._title(_TITLE_ASK, q, tmp_path) == run_ask._trim_question(q)


def test_render_history_under_budget_is_unchanged():
    h = [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "qué tal"}]
    assert run_ask._render_history(h) == "user: hola\nassistant: qué tal"


def test_render_history_drops_oldest_over_budget(monkeypatch):
    monkeypatch.setattr(run_ask, "HISTORY_BUDGET_CHARS", 20)
    h = [{"role": "user", "content": "A" * 10},        # oldest
         {"role": "assistant", "content": "B" * 10},
         {"role": "user", "content": "C" * 10}]         # newest
    out = run_ask._render_history(h)
    assert "A" * 10 not in out                          # oldest dropped
    assert out == "assistant: " + "B" * 10 + "\nuser: " + "C" * 10  # kept, chronological


def test_render_history_keeps_whole_turns(monkeypatch):
    monkeypatch.setattr(run_ask, "HISTORY_BUDGET_CHARS", 15)
    h = [{"role": "user", "content": "X" * 10},
         {"role": "assistant", "content": "Y" * 10},
         {"role": "user", "content": "Z" * 10}]         # newest
    # newest Z (10) fits; adding Y would reach 20 > 15 → stop. Only whole Z kept.
    assert run_ask._render_history(h) == "user: " + "Z" * 10


def test_render_history_single_over_budget_turn_kept_alone(monkeypatch):
    monkeypatch.setattr(run_ask, "HISTORY_BUDGET_CHARS", 5)
    h = [{"role": "assistant", "content": "A" * 100}]
    assert run_ask._render_history(h) == "assistant: " + "A" * 100


def test_retrieve_stitch_widens_hit_with_neighbors(tmp_path):
    machine = _machine(tmp_path, "unused")
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: find\n    retrieve: {mode: lexical, k: 1, stitch: 1}\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [
        {"ref": "r1", "span": [0, 13], "text": "primera parte"},
        {"ref": "r2", "span": [15, 37], "text": "la tensión fundamental"},
        {"ref": "r3", "span": [39, 52], "text": "segunda parte"},
    ])
    rec = run_ask.run_ask(corpus, machine, "find", "tensión")
    assert len(rec["passages"]) == 1
    p = rec["passages"][0]
    assert p["ref"] == "r2"                      # the hit stays the citable anchor
    assert p["refs"] == ["r1", "r2", "r3"]
    assert p["text"] == "primera parte\n\nla tensión fundamental\n\nsegunda parte"


def test_citation_of_stitched_neighbor_is_valid(tmp_path):
    answer = "Y sigue [aaaaaaaaaaaa:r3] la idea."   # cites the neighbor, not the hit
    machine = _machine(tmp_path, answer)
    ask_yaml = (
        "id: a\nversion: 1\nflow: ./flow.yaml\n"
        "index:\n  uses: local.embed\n"
        "asks:\n  - id: answer\n    retrieve: {mode: lexical, k: 1, stitch: 1}\n"
        "    synthesize:\n      uses: api.claude\n      prompt: '${retrieved} ${question}'\n"
        "    check: citations\n")
    corpus = _corpus(tmp_path, ask_yaml)
    _bundle(corpus, "aaaaaaaaaaaa", "general", [
        {"ref": "r2", "span": [0, 22], "text": "la tensión fundamental"},
        {"ref": "r3", "span": [24, 37], "text": "segunda parte"},
    ])
    rec = run_ask.run_ask(corpus, machine, "answer", "tensión")
    assert rec["answer"] == answer
