# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The console sink. emit(event, **data) is the whole contract: the engine
emits every event unconditionally; the observer decides what each level
renders. A later file/JSONL sink is a new class with the same emit, swapped in
at Engine construction — no engine change. This module is the ONLY place that
formats console lines."""
import sys

# minimum level at which each event renders; absent => 0 (always)
_MIN_LEVEL = {
    "dropped": 1, "duplicate": 1, "stage-done": 1, "llm-call": 1,
    "parked": 1, "complete": 1, "retired": 1, "flow-adopted": 1,
    # level 0 (always): failed, quarantined, halted, error, orphan,
    # flow-not-adopted
}


def _secs(ms: int | None) -> str:
    return "—" if ms is None else f"{ms / 1000:.1f}s"


class ConsoleObserver:
    def __init__(self, level: int = 0):
        self.level = level

    def emit(self, event: str, **data) -> None:
        if self.level < _MIN_LEVEL.get(event, 0):
            return
        line = self._render(event, data)
        if line is not None:
            print(line, file=sys.stderr)

    def _render(self, event: str, d: dict) -> str | None:
        did = (d.get("doc_id") or "")[:8]
        if event == "failed":
            return f"FAILED {did} at stage {d['stage']}: {d['reason']}"
        if event == "quarantined":
            return f"QUARANTINED {did} at stage {d['stage']}"
        if event == "halted":
            return f"HALTED {did}: {d['reason']}"
        if event == "error":
            return f"ERROR {did}: {d['reason']}"
        if event == "orphan":
            return f"ORPHAN {d['target']}: {d['detail']}"
        if event == "flow-not-adopted":
            return f"FLOW NOT ADOPTED: {d['reason']}"
        if event == "flow-adopted":
            return f"flow      adopted for new arrivals: version {d['version']}"
        if event == "dropped":
            return f"drop      {did} → {d['entrypoint']}"
        if event == "duplicate":
            return f"dup       {did}  {d['source_name']}"
        if event == "stage-done":
            return (f"stage     {did}  {d['stage']:<13} "
                    f"{d['capability']:<18} {_secs(d.get('duration_ms'))}")
        if event == "parked":
            return f"park      {did}  {d['stage']} → {', '.join(d['fields'])}"
        if event == "complete":
            return f"done      {did}"
        if event == "retired":
            return f"retire    {did}  ({d['rule']})"
        if event == "llm-call":
            return self._render_llm(did, d)
        return None

    def _render_llm(self, did: str, d: dict) -> str:
        fields, conf = d["fields"], d.get("confidence") or {}
        kept = " ".join(
            f"{k}={v}({conf[k]:.2f})" if k in conf else f"{k}={v}"
            for k, v in fields.items())
        gates = d.get("gates") or {}
        parked = d.get("parked") or []
        park_seg = ""
        if parked:
            items = []
            for n in parked:
                if n in conf and n in gates:
                    items.append(f"{n}({conf[n]:.2f}<{gates[n]:.2f})")
                else:
                    items.append(n)
            park_seg = "  parked: " + ", ".join(items)
        line = (f"llm       {did}  {d['stage']:<13} {d['capability']}  "
                f"{_secs(d.get('duration_ms'))}  {kept}{park_seg}")
        if self.level >= 2:
            line += (f"\n--- prompt [{did} {d['stage']}] ---\n{d.get('prompt')}"
                     f"\n--- response ---\n{d.get('response')}\n--- end ---")
        return line
