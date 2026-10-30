# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Saved queries: resolve the corpus-declared folder, render a query file
(frontmatter = definition, body = result or empty), save and list. No clock and
no fallback live here — the folder must be declared or this throws, and the
caller stamps `saved`."""
from pathlib import Path

import yaml

from shapes.corpus.commands._access_cli import format_answer, format_passages

# The order frontmatter keys are written in. Only keys present in the definition
# are emitted — the saved query records the question and the overrides the user
# chose; the ask id pins everything else.
_ORDER = ("ask", "question", "grounding", "mode", "where", "saved")

# Compact provenance lifted into the frontmatter (so `list` and recall can show
# it). The full prompt is large and goes in the body, not here.
_PROV_FRONT = ("model", "input_tokens", "output_tokens", "cost_usd",
               "retrieval_ms", "synthesis_ms", "total_ms")


class QueriesError(Exception):
    """The corpus declares no queries location, or a saved file is malformed."""


def queries_dir(corpus: Path) -> Path:
    """The declared folder, resolved absolute. Throws if `queries:` is absent —
    nothing is created out of thin air."""
    doc = yaml.safe_load((corpus / "corpus.yaml").read_text())
    if "queries" not in doc:
        raise QueriesError(
            f"corpus {corpus} declares no queries location; add `queries: ./queries` "
            "to corpus.yaml")
    return (corpus / doc["queries"]).resolve()


def _provenance_front(prov: dict) -> dict:
    flat = {"model": prov.get("model"), "cost_usd": prov.get("cost_usd"),
            "retrieval_ms": prov.get("retrieval_ms"),
            "synthesis_ms": prov.get("synthesis_ms"), "total_ms": prov.get("total_ms")}
    usage = prov.get("usage") or {}
    flat["input_tokens"] = usage.get("input_tokens")
    flat["output_tokens"] = usage.get("output_tokens")
    return {k: flat[k] for k in _PROV_FRONT if flat.get(k) is not None}


def render_query_file(definition: dict, record: dict | None) -> str:
    front = {k: definition[k] for k in _ORDER if k in definition}
    prov = (record or {}).get("provenance") or {}
    front.update(_provenance_front(prov))            # model/tokens/cost/timing → frontmatter
    text = "---\n" + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + "---\n"
    if record is None:
        return text
    body = format_answer(record) if "answer" in record else format_passages(record["passages"])
    if prov.get("prompt"):                           # the full prompt → body, where size belongs
        body += "\n\n— how this was produced —\n\n" + prov["prompt"]
    return text + "\n" + body + "\n"


def save_query(corpus: Path, name: str, definition: dict, record: dict | None) -> Path:
    folder = queries_dir(corpus)
    folder.mkdir(parents=True, exist_ok=True)        # location declared; dir on demand
    path = folder / f"{name}.md"
    path.write_text(render_query_file(definition, record))
    return path


def list_queries(corpus: Path) -> list[dict]:
    folder = queries_dir(corpus)
    if not folder.is_dir():
        return []
    out: list = []
    for path in sorted(folder.glob("*.md")):
        front = _frontmatter(path)
        front["name"] = path.stem
        out.append(front)
    return out


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise QueriesError(f"saved query {path} has no frontmatter")
    return yaml.safe_load(text.split("---\n", 2)[1]) or {}
