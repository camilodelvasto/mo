# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Validate an assert file against the flow; append ONE assert entry or move
the file to failed/inbox/ with a .reason sibling. Never partial, never
silent. The single human write path."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import yaml

from shapes.corpus.engine import identity, sidecar

_SCHEMA = json.loads(
    (Path(__file__).parent.parent / "schemas" / "assert.v1.json").read_text())


def process(corpus_dir: Path, assert_path: Path, current_flow: dict) -> Path | None:
    """Returns the target meta path on success, None on rejection."""
    try:
        payload = _parse(assert_path)
        name_doc_id = assert_path.name.removesuffix(".assert.yaml").rsplit("-", 1)[-1]
        if name_doc_id != payload["doc_id"]:
            raise ValueError(
                f"filename says {name_doc_id}, payload says {payload['doc_id']}")
        target = identity.find_pair(corpus_dir, payload["doc_id"])
        if target is None:
            raise ValueError(f"no document {payload['doc_id']} in this corpus")
        contract = _contract_for(target.parent, current_flow)
        _validate_fields(payload["fields"], contract)
    except (ValueError, yaml.YAMLError, jsonschema.ValidationError) as exc:
        _reject(corpus_dir, assert_path, str(exc))
        return None
    sidecar.append(target, {
        "id": "assert",
        "by": payload["by"],
        "via": payload.get("via", "inbox"),
        "at": datetime.now(timezone.utc).isoformat(),
        "fields": payload["fields"],
    })
    assert_path.unlink()
    return target


def _parse(assert_path: Path) -> dict:
    payload = yaml.safe_load(assert_path.read_text())
    jsonschema.validate(payload, _SCHEMA)
    return payload


def _contract_for(pair_dir: Path, current_flow: dict) -> dict:
    snapshot = pair_dir / "flow.snapshot.yaml"
    if snapshot.is_file():     # parked/in-flight: the contract the pair parked with
        return yaml.safe_load(snapshot.read_text())
    return current_flow    # completed/retired: the open log, current contract


def _declared(contract: dict) -> dict:
    fields = dict(contract.get("fields") or {})
    for stage in contract.get("pipeline", []):
        fields.update(stage.get("fields") or {})
    return fields


def _validate_fields(fields: dict, contract: dict) -> None:
    declared = _declared(contract)
    for name, value in fields.items():
        decl = declared.get(name)
        if decl is None:
            raise ValueError(f"field not declared by this flow: {name}")
        if not _operator_allowed(decl):
            raise ValueError(
                f"operator may not write {name}: its by: is {decl.get('by', 'model')!r}")
        _check_type(name, value, decl)


def _operator_allowed(decl: dict) -> bool:
    by = decl.get("by", "model")
    return by == "operator" if isinstance(by, str) else "operator" in by


def _check_type(name: str, value, decl: dict) -> None:
    kind = decl["type"]
    if kind == "set":
        if isinstance(value, list):
            return
        if isinstance(value, dict) and set(value) <= {"add", "remove"} and value:
            return
        raise ValueError(f"{name}: a set takes a list or {{add:, remove:}}, got {value!r}")
    if kind == "enum":
        if value not in decl["values"]:
            raise ValueError(f"{name}: {value!r} not in {decl['values']}")
        return
    expected = {"string": str, "number": (int, float), "bool": bool}[kind]
    if not isinstance(value, expected) or isinstance(value, bool) and kind != "bool":
        raise ValueError(f"{name}: expected {kind}, got {value!r}")


def _reject(corpus_dir: Path, assert_path: Path, reason: str) -> None:
    dest_dir = corpus_dir / "failed" / "inbox"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / assert_path.name
    counter = 1
    while dest.exists():                  # never silently overwrite a rejection
        counter += 1
        dest = dest_dir / f"{counter}-{assert_path.name}"
    shutil.move(assert_path, dest)
    dest.with_suffix(".reason").write_text(reason + "\n")
