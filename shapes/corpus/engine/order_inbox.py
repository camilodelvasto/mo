# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Validate an order file against order.v1.json and the corpus. Retire is
actionable now (returns the target meta path for the reactor to move). Reprocess
is a valid order whose engine behaviour lands in a later step — it is refused
here with an explicit 'not yet implemented', the order moved to failed/inbox/
with a .reason. That is a refusal to ACT, never an 'unknown action' (the schema
accepts both). Mirrors assert_inbox: never partial, never silent."""
import json
import shutil
from pathlib import Path

import jsonschema
import yaml

from shapes.corpus.engine import identity

_SCHEMA = json.loads(
    (Path(__file__).parent.parent / "schemas" / "order.v1.json").read_text())


def process(corpus_dir: Path, order_path: Path) -> tuple[str, Path] | None:
    """Returns ('retire', target_meta_path) for an actionable retire, or None
    (rejected, moved to failed/inbox/) for anything not actionable now."""
    try:
        payload = yaml.safe_load(order_path.read_text())
        jsonschema.validate(payload, _SCHEMA)
        name_doc_id = order_path.name.removesuffix(".order.yaml").rsplit("-", 1)[-1]
        if name_doc_id != payload["doc_id"]:
            raise ValueError(
                f"filename says {name_doc_id}, payload says {payload['doc_id']}")
        target = identity.find_pair(corpus_dir, payload["doc_id"])
        if target is None:
            raise ValueError(f"no document {payload['doc_id']} in this corpus")
        if payload["action"] == "reprocess":
            raise ValueError(
                "reprocess: not yet implemented — the reactor lands in a later step")
    except (ValueError, yaml.YAMLError, jsonschema.ValidationError) as exc:
        _reject(corpus_dir, order_path, str(exc))
        return None
    return payload["action"], target          # ('retire', meta_path)


def _reject(corpus_dir: Path, order_path: Path, reason: str) -> None:
    dest_dir = corpus_dir / "failed" / "inbox"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / order_path.name
    counter = 1
    while dest.exists():
        counter += 1
        dest = dest_dir / f"{counter}-{order_path.name}"
    shutil.move(order_path, dest)
    dest.with_suffix(".reason").write_text(reason + "\n")
