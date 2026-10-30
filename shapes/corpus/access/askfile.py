# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Load + resolve ask.yaml, referenced from corpus.yaml's `ask:` key. No
fallbacks: a corpus with no ask.yaml, or a request for an undeclared ask or
profile, throws."""
from pathlib import Path

import yaml

from shapes.corpus.access.errors import AskError


def load_asks(corpus: Path) -> dict:
    corpus_doc = yaml.safe_load((corpus / "corpus.yaml").read_text())
    rel = corpus_doc.get("ask")
    if rel is None:
        raise AskError(f"corpus {corpus} declares no ask.yaml (no `ask:` in corpus.yaml)")
    path = (corpus / rel).resolve()
    if not path.is_file():
        raise AskError(f"ask file not found: {path}")
    return yaml.safe_load(path.read_text())


def resolve_ask(asks: dict, ask_id: str) -> dict:
    for ask in asks.get("asks", []):
        if ask["id"] == ask_id:
            return ask
    raise AskError(f"no ask named {ask_id!r} in this corpus")


def resolve_profile(asks: dict, name: str) -> dict:
    profile = (asks.get("profiles") or {}).get(name)
    if profile is None:
        raise AskError(f"no profile named {name!r} in this corpus")
    return profile


def declared_embedder(corpus: "Path") -> "str | None":
    """Return the embedder capability name from ask.yaml's `index.uses`, or None.

    None means the corpus is lexical (no embedder binding declared).
    Returns None when the corpus has no ask.yaml, or when ask.yaml has no
    `index` block, or when `index` has no `uses` key.
    Raises AskError if `index.uses` is present but empty — that is malformed."""
    try:
        asks = load_asks(corpus)
    except AskError:
        return None
    val = asks.get("index", {}).get("uses")
    if val is not None and not val:
        raise AskError("index.uses is empty — remove it (lexical) or name a capability (embedded)")
    return val
