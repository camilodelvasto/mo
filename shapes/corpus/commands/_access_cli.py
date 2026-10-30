# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Arg parsing + rendering for the access commands. No engine logic lives here."""
import json
from pathlib import Path

from shapes.corpus.access.errors import (AskError, CitationError, HistoryError,
                                         SynthesisError)
from shapes.corpus.engine.errors import CapabilityError


def parse_grounding(raw: str) -> float:
    """Validate a grounding value: a float in [0.0, 1.0]. Throws otherwise."""
    try:
        g = float(raw)
    except ValueError:
        raise SystemExit(f"--grounding must be a number in [0.0, 1.0], got {raw!r}")
    if not (0.0 <= g <= 1.0):
        raise SystemExit(f"--grounding must be in [0.0, 1.0], got {g}")
    return g


def _parse_attachments(raw: str) -> list:
    """--attachments is a JSON array of {data, signature, media_type}, or @path to a
    file holding that JSON. Throws on anything else — no silent empty default."""
    if raw.startswith("@"):
        try:
            text = Path(raw[1:]).read_text()
        except OSError as exc:
            raise SystemExit(f"--attachments file not readable: {exc}")
    else:
        text = raw
    try:
        atts = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--attachments must be JSON: {exc}")
    if not isinstance(atts, list):
        raise SystemExit("--attachments must be a JSON array of {data, signature, media_type}")
    return atts


def _parse_history(raw: str) -> list:
    """--history is a JSON array of {role, content} turns, or @path to a file holding
    that JSON. Throws on anything else — no silent empty default."""
    if raw.startswith("@"):
        try:
            text = Path(raw[1:]).read_text()
        except OSError as exc:
            raise SystemExit(f"--history file not readable: {exc}")
    else:
        text = raw
    try:
        history = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--history must be JSON: {exc}")
    if not isinstance(history, list):
        raise SystemExit("--history must be a JSON array of {role, content} turns")
    for turn in history:                 # shape is enforced here, so _render_history can trust it
        if not (isinstance(turn, dict) and isinstance(turn.get("role"), str)
                and isinstance(turn.get("content"), str)):
            raise SystemExit("--history turns must each be {role: str, content: str}")
    return history


def error_kind(exc: Exception) -> str:
    """Map an access-engine exception to the wire error kind the serve relays.
    SynthesisError is checked before AskError (it subclasses it). An AskError is a
    bad ask name or param (unknown_ask); any other AccessError (filter, passport,
    embed) is an engine_error the serve maps to 500 — so --json always emits a
    typed envelope, never a traceback."""
    if isinstance(exc, CitationError):
        return "citation_check"
    if isinstance(exc, SynthesisError):
        return "synthesis_failed"
    if isinstance(exc, AskError):
        return "unknown_ask"
    if isinstance(exc, HistoryError):
        return "history_malformed"
    if isinstance(exc, CapabilityError):
        return "capability_binding"
    return "engine_error"


def parse_query_args(args: list) -> tuple[str, dict]:
    """First positional is the question; --where/--mode/--k are options."""
    question = None
    opts: dict = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--where":
            opts["where"] = args[i + 1]; i += 2
        elif a == "--mode":
            opts["mode"] = args[i + 1]; i += 2
        elif a == "--k":
            opts["k"] = int(args[i + 1]); i += 2
        elif a == "--grounding":
            opts["grounding"] = parse_grounding(args[i + 1]); i += 2
        elif a == "--history":
            opts["history"] = _parse_history(args[i + 1]); i += 2
        elif a == "--attachments":
            opts["attachments"] = _parse_attachments(args[i + 1]); i += 2
        elif a == "--json":
            opts["json"] = True; i += 1
        elif a == "--stream":
            opts["stream"] = True; i += 1
        elif question is None:
            question = a; i += 1
        else:
            i += 1
    if question is None:
        raise SystemExit('usage: provide a "question"')
    return question, opts


def format_passages(passages: list) -> str:
    """A source per passage: a tiny content-hash for traceability, then the
    document's name (its filename) — the part a reader actually needs."""
    lines: list = []
    for p in passages:
        lines.append(f"[{p['doc_id'][:8]}] {p['name']}")
        lines.append(f"  {p['text'][:300].strip()}")
        lines.append("")
    return "\n".join(lines)


def print_passages(passages: list) -> None:
    print(format_passages(passages))


def format_answer(record: dict) -> str:
    """Reader view: the answer exactly as the model wrote it. Whether sources appear,
    and how, is the prompt's business via the ${sources} placeholder — the renderer
    never rewrites citations or appends a source list of its own."""
    return record["answer"]


def format_provenance(prov: dict) -> str:
    """How an answer was produced: model, tokens, cost, timing, then the full
    prompt. Only the fields present are shown (a find carries timing only; a
    plain-text capability has no model/tokens). The single presentation of
    provenance, shared by the saved file and the TUI details panel."""
    lines: list = []
    if prov.get("model"):
        u = prov.get("usage") or {}
        lines.append(f"model: {prov['model']}")
        lines.append(f"tokens: {u.get('input_tokens')} in / {u.get('output_tokens')} out "
                     f"({u.get('cache_read_input_tokens')} cached)")
        if prov.get("cost_usd") is not None:
            lines.append(f"cost: ${prov['cost_usd']:.4f}")
    timing = [f"{label} {prov[key]}ms"
              for label, key in (("retrieval", "retrieval_ms"),
                                 ("synthesis", "synthesis_ms"), ("total", "total_ms"))
              if prov.get(key) is not None]
    if timing:
        lines.append("timing: " + " · ".join(timing))
    if prov.get("prompt"):
        lines += ["", "— prompt —", "", prov["prompt"]]
    return "\n".join(lines)


def print_answer(record: dict) -> None:
    print(format_answer(record))
