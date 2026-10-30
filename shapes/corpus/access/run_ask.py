# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The ask pipeline: reconcile -> resolve ask -> compose where -> filter ->
retrieve -> (synthesize -> check) -> return the record. Throws on a failed
check; nothing swallows. See GUIDE.md."""
import base64
import datetime
import json
import re
import concurrent.futures
import subprocess
import time
from pathlib import Path

import yaml

from shapes.corpus.access import askfile, attest, filter as flt, index, passport, reconcile, retrieve, stitch
from shapes.corpus.access.errors import (AccessError, AskError, AttachmentError, CitationError,
                                         HistoryError, SynthesisError)
from shapes.corpus.engine import capabilities
from shapes.corpus.engine.errors import CapabilityError

# A citation marker is [<doc_id>:<ref>]. doc_id is the 12-hex content-address
# invariant (owned by identity.py) — anchoring on it rejects incidental
# brackets like [10:30] while NOT coupling to the chunker's ref alphabet, so a
# ref of any shape is still validated against the retrieval set, never skipped.
_CITE = re.compile(r"\[([0-9a-f]{12}):([^\]\s]+)\]")
_N_MAX = 4  # cap on planned retrieval queries per turn — bounds cost and noise

# Grounding directive. A bare number means little to a model, so the level is
# mapped to a CONCRETE behavior band — that is what actually shifts the balance
# between the passages and the model's own knowledge. An ask may override the whole
# directive TEXT via `grounding_directive:`; its numeric `grounding:` sets the LEVEL.
# Source-adherence lives HERE, not in the prime profile or the synthesize body.
def _grounding_band(grounding: float) -> str:
    if grounding >= 0.8:
        return ("Answer using ONLY the provided passages; if they do not contain the "
                "answer, say so and do not go beyond them.")
    if grounding >= 0.5:
        return ("Lead with the passages, but draw on your own knowledge to fill gaps "
                "and add useful context; mark those additions.")
    if grounding >= 0.3:
        return ("Draw substantially on your own knowledge to give a full, useful answer; "
                "use the passages as supporting evidence and to ground or qualify "
                "specific claims, not as the sole source.")
    return ("Answer mainly from your own knowledge; treat the passages as background "
            "context to weave in where relevant.")


# The directive governs source-ADHERENCE only (how much to lean on the passages). It
# does NOT tell the model to cite or name sources — that is presentation, owned by the
# ask's prompt via the ${sources} placeholder, never injected by the engine.
def _grounding_directive(grounding: float) -> str:
    return (f"Source-grounding level: {grounding} on a 0.0-1.0 scale "
            f"(1.0 = only the passages, 0.0 = mainly your own knowledge). "
            f"{_grounding_band(grounding)} Clearly distinguish what you draw from the "
            "passages from what you add from your own knowledge.")


def _validated_grounding(ask: dict, grounding) -> float:
    """Validate and return the effective grounding float. Caller's value wins; falls
    back to the ask's declared default, then 1.0. Raises AskError on bool, non-numeric,
    or out-of-[0,1] values — identical contract on both blocking and streaming paths."""
    if grounding is None:
        grounding = ask.get("grounding", 1.0)
    if isinstance(grounding, bool) or not isinstance(grounding, (int, float)) \
            or not (0.0 <= grounding <= 1.0):
        raise AskError(f"grounding must be a number in [0.0, 1.0], got {grounding!r}")
    return float(grounding)


def _embedder(machine_root: Path):
    def embed(text: str) -> list:
        return passport.embed([{"ref": "__query__", "text": text}], machine_root)[0]["vector"]
    return embed


def _load_flow(corpus: Path) -> dict:
    corpus_doc = yaml.safe_load((corpus / "corpus.yaml").read_text())
    return yaml.safe_load((corpus / corpus_doc["flow"]).resolve().read_text())


def _compose_where(ask: dict, caller_where) -> str | None:
    """ask.where AND caller.where. Caller narrows; it can never widen, because
    AND only ever shrinks the set. None on either side drops that conjunct."""
    parts = [w for w in (ask.get("where"), caller_where) if w]
    if not parts:
        return None
    return " AND ".join(f"({p})" for p in parts)


def _projections(conn) -> dict:
    return {r[0]: json.loads(r[1])
            for r in conn.execute("SELECT doc_id, folded FROM projection")}


# Per-turn history budget (chars, ~4/token). Both decompose and synthesis re-read the
# conversation every turn, so unbounded history makes each turn slower and costlier and
# more exposed to a transient throttle. Keep the most recent whole turns that fit; drop
# the oldest. A single over-budget turn is kept alone — a turn is the atomic unit.
HISTORY_BUDGET_CHARS = 12000
# The vision path carries the conversation structurally, so it needs the same bound in
# its own terms: text rides the char budget, images ride a count. An image costs far
# more than its text (~1.5k tokens each) and every turn re-sends every image of the
# conversation, so without this a long conversation grows until the provider refuses.
# The CURRENT turn's images are never dropped — they are the question.
MAX_ENVELOPE_IMAGES = 8


def _render_history(history: list) -> str:
    """Flatten the request's conversation turns into text for ${history}, keeping only
    the most recent whole turns within HISTORY_BUDGET_CHARS (oldest dropped). Each turn
    is {role, content}; client-supplied, untrusted — the same trust level as the
    question. The declared scope, not history, is what protects the corpus; trimming
    changes only how much untrusted history reaches the model, never the scope."""
    kept: list = []
    total = 0
    for turn in reversed(history):                 # newest first
        clen = len(turn["content"])
        if kept and total + clen > HISTORY_BUDGET_CHARS:
            break                                  # adding this older turn exceeds the budget
        kept.append(turn)
        total += clen
    kept.reverse()                                 # back to chronological order
    return "\n".join(f"{t['role']}: {t['content']}" for t in kept)


def _plan_queries(ask: dict, question: str, history: list, machine_root: Path) -> list:
    """Plan the standalone retrieval queries for a turn. Spawns the ask's declared
    decompose capability (reads stdin; stdout is one query per line, or an envelope
    whose `answer` holds the lines). Resolves references from history AND splits a
    multi-intent turn into several queries. Returns 1..N_MAX queries; synthesis still
    sees the original question. Empty output is a failed plan, never a silent fallback."""
    spec = ask["decompose"]
    prompt = spec["prompt"].replace("${history}", _render_history(history))
    prompt = prompt.replace("${question}", question)
    table = capabilities.load_table(machine_root)
    binding = capabilities.resolve(spec["uses"], table)
    if binding["reads"] != "stdin":
        raise AskError(f"decompose capability {spec['uses']} must read stdin")
    proc = subprocess.run(binding["run"], input=prompt.encode(), capture_output=True)
    if proc.returncode != 0:
        raise SynthesisError(
            f"decompose failed: {proc.stderr.decode(errors='replace').strip()}")
    out = proc.stdout.decode().strip()
    if binding.get("emits") == "envelope":   # e.g. api.claude-json: queries live in `answer`
        out = json.loads(out).get("answer", "").strip()
    queries = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not queries:                          # empty plan is a failure, not a default
        raise SynthesisError("decompose produced no queries")
    return queries[:_N_MAX]


_TITLE_PROMPT = (
    "Produce a 3-6 word label naming this conversation, in the same language as "
    "the question. Return only the label, with no quotes or trailing punctuation.\n\n"
    "Question: ")


def _trim_question(question: str) -> str:
    """The declared baseline conversation label: the question's first 6 words on a
    word boundary, with an ellipsis when it runs longer. A titled ask ALWAYS has
    this deterministic label; the LLM title step only refines it (see _title)."""
    words = question.split()
    if len(words) <= 6:
        return " ".join(words)
    return " ".join(words[:6]) + "…"


# The wire shape a synthesize binding reads is DECLARED in the binding table:
#   reads: stdin     — a rendered prompt (the text path)
#   reads: envelope  — the multimodal envelope {system, messages} (the vision path)
# The engine never guesses: the shape an ask needs is checked against the shape its
# binding declares, and a mismatch is a binding error at request time — before any
# retrieval is spent and before a single byte reaches the model.
def _require_reads(binding: dict, capability_name: str, shape: str) -> None:
    declared = binding.get("reads")
    if declared != shape:
        raise CapabilityError(
            f"synthesize capability {capability_name} declares reads: {declared!r}; "
            f"this ask needs reads: {shape} — bind {capability_name} to a binding that "
            f"reads a{'n' if shape[0] in 'aeiou' else ''} {shape}")


def _synthesize_binding(ask: dict, machine_root: Path) -> tuple[dict, str, str]:
    """(binding, capability name, the wire shape this ask needs)."""
    name = ask["synthesize"]["uses"]
    table = capabilities.load_table(machine_root)
    binding = capabilities.resolve(name, table)
    shape = "envelope" if ask.get("attachments") else "stdin"
    _require_reads(binding, name, shape)
    return binding, name, shape


_TITLE_SYSTEM = "You label conversations."


def _title(ask: dict, question: str, machine_root: Path) -> str:
    """A polished conversation label from the question — a bounded step off the
    ask's OWN synthesize capability (tiny in, tiny out: it cannot truncate). By
    declared contract the label falls back to _trim_question on a runtime failure
    of the title call (non-zero exit, empty label, bad envelope, spawn error): the
    title is best-effort and never holds the answer hostage. A broken binding still
    surfaces — synthesis shares it and would fail too."""
    baseline = _trim_question(question)
    binding, name, shape = _synthesize_binding(ask, machine_root)
    if shape == "envelope":
        # An envelope reader has one wire shape: the title rides the stream binding as
        # a tiny text-only envelope, tokens joined. No second run: binding to keep in step.
        envelope = {"system": _TITLE_SYSTEM, "messages": [
            {"role": "user", "content": [{"type": "text", "text": _TITLE_PROMPT + question}]}]}
        try:
            out = "".join(_stream_capability(binding, json.dumps(envelope).encode(), {}, name))
        except (AccessError, OSError, ValueError):   # a failed title degrades, never kills the answer
            return baseline
        return out.strip().strip('"').strip() or baseline
    try:
        proc = subprocess.run(binding["run"], input=(_TITLE_PROMPT + question).encode(),
                              capture_output=True)
        if proc.returncode != 0:
            return baseline
        out = proc.stdout.decode().strip()
        if binding.get("emits") == "envelope":
            out = json.loads(out).get("answer", "").strip()
        out = out.strip().strip('"').strip()
        return out or baseline
    except (OSError, ValueError, AttributeError):   # decode/parse/shape failures degrade, never kill the answer
        return baseline


def run_ask(corpus: Path, machine_root: Path, ask_id: str, question: str,
            where=None, mode=None, k=None, grounding: float | None = None,
            history=None, attachments=None) -> dict:
    if attachments:
        raise AskError("attachments require the streaming path")
    reconcile.reconcile(corpus, machine_root)         # every ask reconciles first
    asks = askfile.load_asks(corpus)
    ask = askfile.resolve_ask(asks, ask_id)
    flow = _load_flow(corpus)

    # grounding: the caller's value wins; otherwise the ask's declared default
    # (`grounding:`, defaulting to 1.0 = pure RAG). A web turn sends none, so the
    # ask's level is what governs the answer.
    grounding = _validated_grounding(ask, grounding)

    # decompose: plan the standalone retrieval queries for this turn (references
    # resolved from history; a multi-intent turn split into several). Runs on EVERY
    # turn when declared — turn 1 included, closing the "no planning on the first
    # message" gap. An ask without decompose retrieves on the raw question.
    planned = (_plan_queries(ask, question, history or [], machine_root)
               if ask.get("decompose") else None)
    queries = planned if planned is not None else [question]

    t_start = time.monotonic()
    conn = index.open_index(corpus)
    try:
        projections = _projections(conn)
        scope = flt.doc_ids_for(_compose_where(ask, where), flow, projections)
        spec = ask.get("retrieve", {})
        # grounding 0.0 → pure model knowledge, no retrieval (overrides the ask's mode)
        eff_mode = "none" if grounding == 0.0 else (mode or spec.get("mode", "hybrid"))
        eff_k = k or spec.get("k", 8)
        t_retrieve = time.monotonic()
        passages = retrieve.retrieve_many(conn, eff_mode, eff_k, scope, queries,
                                          _embedder(machine_root))
        passages = stitch.stitch(conn, passages, spec.get("stitch", 0))
        retrieval_ms = round((time.monotonic() - t_retrieve) * 1000)
    finally:
        conn.close()
    _attach_names(passages, projections)

    if "synthesize" not in ask:
        prov = {"retrieval_ms": retrieval_ms,
                "total_ms": round((time.monotonic() - t_start) * 1000)}
        record = {"ask": ask_id, "question": question, "passages": passages,
                  "provenance": prov}
        if planned is not None:
            record["queries"] = planned
        return record

    t_synth = time.monotonic()
    # A titled ask names the conversation once (first turn only). The label comes
    # from the question, so it runs in parallel with synthesis — it never adds
    # latency and can never truncate the answer (see _title). Synthesis returns
    # plain prose; the citation gate below scans that prose directly.
    want_title = bool(ask["synthesize"].get("titled")) and not history
    title = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        title_future = pool.submit(_title, ask, question, machine_root) if want_title else None
        answer, prompt, meta = _synthesize(ask, asks, question, passages,
                                           machine_root, grounding, history or [])
        if title_future is not None:
            title = title_future.result()
    synthesis_ms = round((time.monotonic() - t_synth) * 1000)
    if passages and ask.get("check") == "citations":   # opt-in: only an ask that declares
        _check_citations(answer, passages)              # `check: citations` is gated, and it
                                                        # is then that ask's prompt that must
                                                        # instruct [doc:chunk] markers
    prov = {"retrieval_ms": retrieval_ms, "synthesis_ms": synthesis_ms,
            "total_ms": round((time.monotonic() - t_start) * 1000), "prompt": prompt}
    if meta:                           # present only when the capability emits an envelope
        prov["model"] = meta.get("model")
        prov["usage"] = meta.get("usage")
        prov["cost_usd"] = meta.get("cost_usd")
    record = {"ask": ask_id, "question": question, "answer": answer,
              "passages": passages, "provenance": prov}
    if title is not None:              # additive: only a titled ask names the conversation
        record["title"] = title
    if planned is not None:
        record["queries"] = planned
    return record


def _attach_names(passages: list, projections: dict) -> None:
    """Label each passage with its document's source_name (the original filename),
    so a source can be shown as a name, not just a content hash. Falls back to the
    doc_id when a projection carries no source_name (a label, never silent data)."""
    for p in passages:
        proj = projections.get(p["doc_id"], {})
        p["name"] = proj.get("source_name") or p["doc_id"]


def _render_retrieved(passages: list) -> str:
    """Passages for the model, labelled by source NAME (not an internal doc:chunk id).
    Any attribution the model echoes is then a readable name, and whether to cite at
    all is the prompt's business — the engine hardcodes no reference format."""
    return "\n\n".join(f"[{p.get('name') or p['doc_id']}] {p['text']}" for p in passages)


def _today() -> str:
    """Current date (ISO, e.g. 2026-07-03) for the ${today} placeholder. A function so
    the ask can tell the model what 'now' is — the corpus holds dated events the model's
    training may read as future. Isolated here so tests can pin it."""
    return datetime.date.today().isoformat()


def _render_sources(passages: list) -> str:
    """The ${sources} placeholder: a compact, deduped source list — one line per unique
    document (its name), in retrieval order. Available for the prompt author to place;
    the engine never injects it on its own (no ${sources} in the prompt → no list)."""
    seen, lines = set(), []
    for p in passages:
        if p["doc_id"] not in seen:
            seen.add(p["doc_id"])
            lines.append(p.get("name") or p["doc_id"])
    return "\n".join(lines)


def _build_synthesis_prompt(ask: dict, asks: dict, question: str, passages: list,
                            grounding: float, history: list) -> str:
    """Assemble the full prompt string from directive + prime + retrieved + placeholders.
    Called by both _synthesize (blocking) and _synthesize_stream so the prompt never
    drifts between the two paths."""
    override = ask.get("grounding_directive")
    directive = (override.replace("${grounding}", f"{grounding}") if override
                 else _grounding_directive(grounding))
    prompt = ask["synthesize"]["prompt"]
    # Declarative grounding: declaring `retrieve:` grounds the ask, and the engine wires
    # the retrieved passages into the model context. `${retrieved}` is an OPTIONAL override
    # for authors who want to control placement; when it is absent the engine injects the
    # passages into the system block, right after the grounding directive that already
    # references them. Either way retrieved sources reach the model — never silently dropped.
    rendered = _render_retrieved(passages)
    if "${retrieved}" in prompt:                    # author placed the passages explicitly
        prompt = prompt.replace("${retrieved}", rendered)
        auto_passages = None
    else:                                           # engine wires them in (no author plumbing)
        auto_passages = rendered if passages else None
    prompt = prompt.replace("${sources}", _render_sources(passages))
    prompt = prompt.replace("${today}", _today())
    prompt = prompt.replace("${history}", _render_history(history))
    prompt = prompt.replace("${question}", question)
    system = directive
    if auto_passages:                               # co-located with the directive that cites them
        system = system + "\n\nRetrieved passages:\n" + auto_passages
    if ask.get("prime"):
        profile = askfile.resolve_profile(asks, ask["prime"])
        system = system + "\n\n" + profile["system"].rstrip()
    return system + "\n\n" + prompt


def _collect_attachments(history: list, attachments: list) -> list:
    """The DISTINCT images in the conversation (history turns + the current turn),
    de-duped by signature. It counts against max_count only — it is never the set
    that is verified or sent: a repeated signature may carry other bytes."""
    seen, out = set(), []
    for turn in history or []:
        for a in turn.get("attachments") or []:
            if a["signature"] not in seen:
                seen.add(a["signature"]); out.append(a)
    for a in attachments or []:
        if a["signature"] not in seen:
            seen.add(a["signature"]); out.append(a)
    return out


def _envelope_attachments(history: list, attachments: list) -> list:
    """Every attachment that can enter the envelope, as sent: each history turn's
    and the current turn's, no dedup. This is the set that is verified."""
    return [a for turn in history or [] for a in turn.get("attachments") or []] + list(attachments or [])


def _check_history(history: list) -> None:
    """The history strictly alternates user/assistant, opening with the user and
    closing with the assistant — the current turn is the user's — and only user turns
    carry attachments. The provider refuses any other shape; refuse it here by name,
    never merge or drop turns to fit."""
    for i, turn in enumerate(history or []):
        expected = "user" if i % 2 == 0 else "assistant"
        if turn["role"] != expected:
            raise HistoryError(f"history turn {i} is {turn['role']!r}, expected {expected!r}: "
                               f"turns must alternate user/assistant, opening with the user")
        if turn["role"] == "assistant" and turn.get("attachments"):
            raise HistoryError(f"history turn {i} is the assistant's and carries attachments: "
                               f"images belong to the user's turns")
    if history and history[-1]["role"] != "assistant":
        raise HistoryError("history ends on a user turn; it must close with the assistant")


def _verify_attachments(machine_root, ask_id: str, attachments: list) -> None:
    """Check the box's own cleanliness token on every attachment before it enters the
    model envelope. The token names the ask that verified it: one issued under another
    ask's policy does not verify here. A bad or absent signature is a hard stop — never verify-inline."""
    if not attachments:
        return
    secret = attest.load_secret(machine_root)
    for a in attachments:
        try:
            data = base64.b64decode(a["data"], validate=True)   # strict: the string verified is the string forwarded
            attest.verify(secret, ask_id, data, a["media_type"], a["signature"])
        except (attest.AttestError, KeyError, ValueError) as exc:
            raise AttachmentError("attachment_untrusted",
                f"an attachment failed verification: {exc}")


def _image_blocks(attachments: list) -> list:
    return [{"type": "image", "media_type": a["media_type"], "data": a["data"]}
            for a in (attachments or [])]


def _bounded_history(history: list, current_images: int) -> list:
    """The most recent whole turns that fit BOTH bounds: HISTORY_BUDGET_CHARS of text
    and MAX_ENVELOPE_IMAGES images across the envelope (the current turn's images are
    counted first — they are never dropped). Oldest turns go first, whole. A single
    over-budget turn is kept alone for TEXT only; the image bound has no exception.
    An image cut also drops the older text-only turns: the kept history is one
    contiguous run of the newest turns. It opens with a user turn: a conversation
    that opens with the assistant is refused by the provider."""
    kept, chars, images = [], 0, current_images
    for turn in reversed(history):                 # newest first
        clen = len(turn["content"])
        n_img = len(turn.get("attachments") or [])
        if images + n_img > MAX_ENVELOPE_IMAGES:
            break                                  # images are never over-kept, not even the newest turn
        if kept and chars + clen > HISTORY_BUDGET_CHARS:
            break                                  # this older turn does not fit; nor will any before it
        kept.append(turn)
        chars += clen
        images += n_img
    kept.reverse()                                 # back to chronological order
    while kept and kept[0]["role"] != "user":      # the conversation opens with the user
        kept.pop(0)
    return kept


def _build_vision_envelope(ask: dict, asks: dict, question: str, passages: list,
                           grounding: float, history: list, attachments: list) -> dict:
    """The multimodal envelope for api.claude-vision: a system block carrying the same
    RAG context the text path folds in (grounding directive + retrieved passages +
    prime), and a messages list reconstructing the conversation with image blocks on
    the turns that carried them. The current question + its images are the last turn."""
    override = ask.get("grounding_directive")
    directive = (override.replace("${grounding}", f"{grounding}") if override
                 else _grounding_directive(grounding))
    system = directive
    rendered = _render_retrieved(passages)
    prompt = ask["synthesize"]["prompt"]
    # Mirror the text path's ${retrieved} contract: if the prompt author placed the
    # placeholder, substitute passages there and do NOT also inject them into the system
    # block (which would duplicate them). When absent, the engine wires them in.
    if "${retrieved}" in prompt:                    # author placed the passages explicitly
        prompt = prompt.replace("${retrieved}", rendered)
    else:                                           # engine wires them in (no author plumbing)
        if passages:
            system = system + "\n\nRetrieved passages:\n" + rendered
    if ask.get("prime"):
        profile = askfile.resolve_profile(asks, ask["prime"])
        system = system + "\n\n" + profile["system"].rstrip()

    messages = []
    for turn in _bounded_history(history or [], len(attachments or [])):
        content = [{"type": "text", "text": turn["content"]}]
        content += _image_blocks(turn.get("attachments"))
        messages.append({"role": turn["role"], "content": content})
    prompt = prompt.replace("${sources}", _render_sources(passages))
    prompt = prompt.replace("${today}", _today())
    # ${history}: the vision path represents the conversation STRUCTURALLY as messages
    # (not as flattened text), so this placeholder is intentionally substituted with
    # the empty string — the history is already present in the messages list above.
    prompt = prompt.replace("${history}", "")
    prompt = prompt.replace("${question}", question)
    current = [{"type": "text", "text": prompt}] + _image_blocks(attachments)
    messages.append({"role": "user", "content": current})
    return {"system": system, "messages": messages}


def _synthesize(ask: dict, asks: dict, question: str, passages: list,
                machine_root: Path, grounding: float,
                history: list) -> tuple[str, str, dict | None]:
    """Returns (answer, prompt, meta). `prompt` is the full text sent to the model —
    the grounding directive, the prime profile, the synthesize body with the passages,
    conversation history and question resolved. `meta` carries model/usage/cost when
    the capability declares `emits: envelope`, else None."""
    binding, name, shape = _synthesize_binding(ask, machine_root)
    if shape == "envelope":
        # Blocking twin of _synthesize_stream_vision: the same envelope down the
        # stream: binding, tokens joined. Attachment verification lives on the
        # streaming path — no image bytes may enter the envelope from here.
        if any(turn.get("attachments") for turn in history or []):
            raise AskError("history attachments require the streaming path")
        _check_history(history or [])
        envelope = _build_vision_envelope(ask, asks, question, passages,
                                          grounding, history, [])
        meta = {}
        answer = "".join(_stream_capability(binding, json.dumps(envelope).encode(),
                                            meta, name))
        # The contract: `prompt` is the FULL text sent. Every block on this path is
        # text (attachments are refused above), so the envelope flattens losslessly.
        prompt = envelope["system"] + "\n\n" + "\n\n".join(
            "".join(b["text"] for b in m["content"]) for m in envelope["messages"])
        return answer, prompt, meta or None

    prompt = _build_synthesis_prompt(ask, asks, question, passages, grounding, history)
    proc = subprocess.run(binding["run"], input=prompt.encode(), capture_output=True)
    if proc.returncode != 0:
        raise SynthesisError(f"synthesis failed: {proc.stderr.decode(errors='replace').strip()}")
    out = proc.stdout.decode().strip()
    if binding.get("emits") == "envelope":          # structured: answer + provenance
        env = json.loads(out)
        answer = env["answer"]
        meta = {"model": env.get("model"), "usage": env.get("usage"),
                "cost_usd": env.get("cost_usd")}
    else:                                           # plain text: answer only
        answer, meta = out, None
    return answer, prompt, meta


def _stream_capability(binding: dict, payload: bytes, meta_out: dict, capability_name: str):
    """Spawn a capability's `stream:` binding, feed `payload` on stdin, yield token
    text, fill meta_out from the terminal `done`. Shared by the text and vision paths
    so their streaming semantics cannot drift. Raises on a missing stream binding or a
    non-zero exit — no fallback to blocking."""
    stream_cmd = binding.get("stream")
    if not stream_cmd:
        raise AskError(f"synthesize capability {capability_name} declares no "
                       f"stream: binding — cannot stream this ask")
    proc = subprocess.Popen(stream_cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.stdin.write(payload)
    proc.stdin.close()
    for raw in proc.stdout:
        line = raw.decode(errors="replace").strip() if isinstance(raw, bytes) else raw.strip()
        if not line:
            continue
        ev = json.loads(line)
        kind = ev.get("event")
        if kind == "token":
            yield ev["text"]
        elif kind == "done":
            meta_out.update(model=ev.get("model"), usage=ev.get("usage"),
                            cost_usd=ev.get("cost_usd"))
        elif kind == "error":
            raise SynthesisError(ev.get("detail") or "synthesis failed")
    if proc.wait() != 0:
        raise SynthesisError(proc.stderr.read().decode(errors="replace").strip()
                             or "synthesis failed")


def _synthesize_stream(ask, asks, question, passages, machine_root, grounding,
                       history, meta_out: dict):
    """Yield answer token strings via the capability's `stream:` binding, filling
    meta_out with model/usage/cost from the terminal `done` line. Raises AskError if
    the capability declares no stream binding (no fallback to blocking)."""
    prompt = _build_synthesis_prompt(ask, asks, question, passages, grounding, history)
    name = ask["synthesize"]["uses"]
    binding = capabilities.resolve(name, capabilities.load_table(machine_root))
    _require_reads(binding, name, "stdin")
    yield from _stream_capability(binding, prompt.encode(), meta_out, name)


def _synthesize_stream_vision(ask, asks, question, passages, machine_root, grounding,
                              history, attachments, meta_out: dict):
    """Yield answer token strings via the capability's `stream:` binding using a
    multimodal envelope. Vision path: attachments are folded into the messages list
    alongside the prompt. Uses the same `_stream_capability` loop as the text path
    so streaming semantics cannot drift between the two."""
    envelope = _build_vision_envelope(ask, asks, question, passages, grounding,
                                      history, attachments)
    name = ask["synthesize"]["uses"]
    binding = capabilities.resolve(name, capabilities.load_table(machine_root))
    _require_reads(binding, name, "envelope")
    yield from _stream_capability(binding, json.dumps(envelope).encode(), meta_out, name)


def _stream_error_kind(exc) -> str:
    if isinstance(exc, AttachmentError):
        return exc.kind
    if isinstance(exc, HistoryError):
        return "history_malformed"
    if isinstance(exc, CitationError):
        return "citation_check"
    if isinstance(exc, SynthesisError):
        return "synthesis_failed"
    if isinstance(exc, CapabilityError):
        return "capability_binding"
    return "unknown_ask"


def run_ask_stream(corpus, machine_root, ask_id, question, *, where=None, mode=None,
                   k=None, grounding=None, history=None, attachments=None):
    """Streaming sibling of run_ask: yields NDJSON-ready event dicts. Reuses the same
    reconcile/decompose/retrieve; streams synthesis. Emits a `step` for each stage that
    declares a `status`. Errors surface as an `error` event (never a partial `done`).
    When the ask declares `attachments:` and attachments are present, routes to the
    vision path (_synthesize_stream_vision); otherwise uses the text path."""
    try:
        reconcile.reconcile(corpus, machine_root)
        asks = askfile.load_asks(corpus)
        ask = askfile.resolve_ask(asks, ask_id)
        flow = _load_flow(corpus)
        grounding = _validated_grounding(ask, grounding)

        # The declaration decides the path, not the turn: an ask that accepts
        # attachments binds synthesize to a vision capability, which reads a
        # multimodal envelope — a text-only turn is an envelope with zero images,
        # never a bare prompt that binding cannot parse. Attachments on an ask that
        # declares none are refused by the schema/service before reaching here.
        use_vision = bool(ask.get("attachments"))
        if "synthesize" in ask:
            _synthesize_binding(ask, machine_root)   # declared wire shape matches, or refuse now
        carried = _collect_attachments(history or [], attachments or [])
        if use_vision:
            _check_history(history)
            # The box is the authority on the declared bounds; the client's pre-check
            # is a hint. max_count limits the DISTINCT images in the conversation
            # (`carried`); MAX_ENVELOPE_IMAGES bounds the raw images sent in one envelope.
            policy = ask["attachments"]
            if len(attachments or []) > MAX_ENVELOPE_IMAGES:
                raise AttachmentError("too_many",
                    f"{len(attachments)} attachments on this turn; the envelope carries "
                    f"at most {MAX_ENVELOPE_IMAGES}")
            if "max_count" in policy and len(carried) > policy["max_count"]:
                raise AttachmentError("too_many",
                    f"{len(carried)} attachments in this conversation; the ask allows "
                    f"at most {policy['max_count']}")
            _verify_attachments(machine_root, ask_id, _envelope_attachments(history, attachments))
        elif carried:
            raise AttachmentError("no_attachments_policy",
                f"ask {ask_id!r} declares no attachments policy; refusing to drop "
                f"{len(carried)} attachment(s) silently")

        dstep = (ask.get("decompose") or {}).get("status")
        if dstep:
            yield {"event": "step", "text": dstep}
        planned = (_plan_queries(ask, question, history or [], machine_root)
                   if ask.get("decompose") else None)
        queries = planned if planned is not None else [question]

        rstep = (ask.get("retrieve") or {}).get("status")
        if rstep:
            yield {"event": "step", "text": rstep}
        conn = index.open_index(corpus)
        try:
            projections = _projections(conn)
            scope = flt.doc_ids_for(_compose_where(ask, where), flow, projections)
            spec = ask.get("retrieve", {})
            eff_mode = "none" if grounding == 0.0 else (mode or spec.get("mode", "hybrid"))
            eff_k = k or spec.get("k", 8)
            passages = retrieve.retrieve_many(conn, eff_mode, eff_k, scope, queries,
                                              _embedder(machine_root))
            passages = stitch.stitch(conn, passages, spec.get("stitch", 0))
        finally:
            conn.close()
        _attach_names(passages, projections)

        if "synthesize" not in ask:
            raise AskError(f"ask {ask_id!r} has no synthesize step; cannot stream")

        want_title = bool(ask["synthesize"].get("titled")) and not history
        title = None
        answer_parts, meta = [], {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            title_future = pool.submit(_title, ask, question, machine_root) if want_title else None
            stream = (_synthesize_stream_vision(ask, asks, question, passages, machine_root,
                                                grounding, history or [], attachments or [], meta)
                      if use_vision else
                      _synthesize_stream(ask, asks, question, passages, machine_root,
                                         grounding, history or [], meta))
            for tok in stream:
                answer_parts.append(tok)
                yield {"event": "token", "text": tok}
            if title_future is not None:
                title = title_future.result()

        answer = "".join(answer_parts)
        if passages and ask.get("check") == "citations":
            _check_citations(answer, passages)      # raises CitationError → error event below

        # sources: deduped by name, first-appearance order, positional [1..n].
        # Streamed ONLY when the ask declares `sources: true` — showing them is an
        # explicit declaration; absence (or false) streams none, so a persona ask
        # uses the corpus without exposing it. No hidden default.
        if ask.get("sources") is True:
            seen, srcs = set(), []
            for p in passages:
                nm = p.get("name") or p["doc_id"]
                if nm not in seen:
                    seen.add(nm)
                    srcs.append({"n": len(srcs) + 1, "title": nm})
            yield {"event": "sources", "sources": srcs}
        if title is not None:
            yield {"event": "title", "text": title}
        yield {"event": "done", "model": meta.get("model"),
               "usage": meta.get("usage"), "cost_usd": meta.get("cost_usd")}
    except (AccessError, CapabilityError) as exc:
        yield {"event": "error", "kind": _stream_error_kind(exc), "detail": str(exc)}


def _check_citations(answer: str, passages: list) -> None:
    # a stitched passage lists every member chunk in `refs`; each is citable
    available = {(p["doc_id"], r) for p in passages
                 for r in p.get("refs", [p["ref"]])}
    for doc_id, ref in _CITE.findall(answer):
        if (doc_id, ref) not in available:
            raise CitationError(
                f"fabricated citation [{doc_id}:{ref}] — not in the retrieval set")
