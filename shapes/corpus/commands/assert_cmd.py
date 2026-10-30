# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus assert <path> <doc_id> field=value [field+=a,b] [field-=c] ...
Writes ONE assert file into inbox/ — it never touches a sidecar."""
import sys
from pathlib import Path

import yaml
from ulid import ULID

from shapes.corpus.commands._read import resolve_corpus


def run(corpus_root: Path, instance: str, args: list) -> None:
    if len(args) < 3:
        print("usage: mo corpus assert <path> <doc_id> <field>=<value> ...",
              file=sys.stderr)
        sys.exit(1)
    corpus = resolve_corpus(args)
    doc_id = args[1]
    fields: dict = {}
    for spec in args[2:]:
        name, value = _parse_spec(spec)
        if isinstance(value, dict):                # set op: merge add/remove
            fields.setdefault(name, {}).update(value)
        else:
            fields[name] = value
    payload = {"doc_id": doc_id, "by": "operator", "via": "cli", "fields": fields}
    inbox = corpus / "inbox"
    inbox.mkdir(exist_ok=True)
    tmp = inbox / f".{ULID()}.tmp"
    tmp.write_text(yaml.safe_dump(payload, sort_keys=False))
    final = inbox / f"{ULID()}-{doc_id}.assert.yaml"
    tmp.rename(final)                              # atomic: the engine never
    print(f"wrote {final.name}")                   # sees a half-written assert


def _parse_spec(spec: str):
    for op, key in (("+=", "add"), ("-=", "remove")):
        if op in spec:
            name, items = spec.split(op, 1)
            return name, {key: [v.strip() for v in items.split(",") if v.strip()]}
    if "=" not in spec:
        print(f"not an assignment: {spec}", file=sys.stderr)
        sys.exit(1)
    name, value = spec.split("=", 1)
    return name, value
