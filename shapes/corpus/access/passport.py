# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Discover/write/verify index/passport.yaml. The passport records ground-truth
embedder identity — capability + the model ollama served + the discovered dim —
so a swapped embedder is caught at open, never re-embedded silently."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from shapes.corpus.access.errors import PassportError
from shapes.corpus.engine import capabilities

_PROBE_REF = "__passport_probe__"
_PROBE_TEXT = "moui corpus access passport probe"


def _path(corpus: Path) -> Path:
    return corpus / "index" / "passport.yaml"


def embed(chunks: list[dict], machine_root: Path) -> list[dict]:
    """Run chunks through the bound local.embed; return [{ref, vector, dim, model}].
    Shared by passport probing and reconcile. No fallbacks — non-zero throws."""
    table = capabilities.load_table(machine_root)
    binding = capabilities.resolve("local.embed", table)
    stdin = ("".join(json.dumps({"ref": c["ref"], "text": c["text"]}) + "\n"
                     for c in chunks)).encode()
    proc = subprocess.run(binding["run"], input=stdin, capture_output=True)
    if proc.returncode != 0:
        raise PassportError(
            f"local.embed failed: {proc.stderr.decode(errors='replace').strip()}")
    out = [json.loads(l) for l in proc.stdout.decode().splitlines() if l.strip()]
    if len(out) != len(chunks):
        raise PassportError(f"embedder returned {len(out)} vectors for {len(chunks)} chunks")
    by_ref = {r["ref"]: r for r in out}
    missing = [c["ref"] for c in chunks if c["ref"] not in by_ref]
    if missing:
        raise PassportError(f"embedder dropped refs: {missing}")
    return [by_ref[c["ref"]] for c in chunks]


def probe(corpus: Path, machine_root: Path) -> dict:
    rec = embed([{"ref": _PROBE_REF, "text": _PROBE_TEXT}], machine_root)[0]
    return {"capability": "local.embed", "model": rec["model"], "dimension": rec["dim"]}


def write(corpus: Path, identity: dict) -> None:
    doc = dict(identity)
    doc["retrieval"] = "embedded"
    doc["built_at"] = datetime.now(timezone.utc).isoformat()
    _path(corpus).parent.mkdir(parents=True, exist_ok=True)
    _path(corpus).write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))


def write_lexical(corpus: Path) -> None:
    """Write a lexical passport — no embedder, no dimension."""
    doc = {"retrieval": "lexical", "built_at": datetime.now(timezone.utc).isoformat()}
    _path(corpus).parent.mkdir(parents=True, exist_ok=True)
    _path(corpus).write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))


def read(corpus: Path) -> dict | None:
    p = _path(corpus)
    return yaml.safe_load(p.read_text()) if p.is_file() else None


def verify(corpus: Path, machine_root: Path, *, lexical: bool = False,
           probe_live: bool = True) -> dict:
    """probe_live=False skips the live embedder probe on the embedded path —
    for lexical reads over an embedded index, which use no embedder. The kind
    check always runs. Anything that writes vectors or embeds a query must
    keep probe_live=True."""
    stored = read(corpus)
    if stored is None:
        raise PassportError(f"no passport at {_path(corpus)} — run mo corpus index")

    stored_is_lexical = "dimension" not in stored

    # Kind mismatch: lexical index cannot serve as embedded, or vice versa.
    if stored_is_lexical and not lexical:
        raise PassportError(
            "kind mismatch: index was built as lexical but corpus now declares an embedder. "
            "Run `mo corpus index --rebuild` to re-index.")
    if not stored_is_lexical and lexical:
        raise PassportError(
            "kind mismatch: index was built as embedded but corpus now declares no embedder. "
            "Run `mo corpus index --rebuild` to re-index.")

    if lexical:
        # No embedder probe needed — stored passport is valid for a lexical corpus.
        return stored

    if not probe_live:
        return stored

    # Embedded path: probe and compare.
    live = probe(corpus, machine_root)
    for key in ("capability", "model", "dimension"):
        if stored.get(key) != live[key]:
            raise PassportError(
                f"embedder {key} diverged: index built with "
                f"{stored.get(key)!r}, machine now serves {live[key]!r}. "
                "Run `mo corpus index --rebuild` to re-embed.")
    return live
