# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The projection: log -> flat description. THE shared primitive.

Scalar last-write-wins; set union-minus-removes, in log order; proposed:
ignored. Imported, never reimplemented.
"""
from shapes.corpus.engine.errors import ContractError, SidecarError


def fold(entries: list[dict]) -> dict:
    projection: dict = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SidecarError(f"log entry is not a mapping: {entry!r}")
        fields = entry.get("fields", {})
        if fields is None:
            raise SidecarError(f"entry {entry.get('id', '?')!r} has fields: null")
        for name, value in fields.items():
            if isinstance(value, dict) and ("add" in value or "remove" in value):
                _apply_set(projection, name, value)
            elif isinstance(value, list):
                _apply_set(projection, name, {"add": value})
            else:
                projection[name] = value
    return projection


def _apply_set(projection: dict, name: str, op: dict) -> None:
    existing = projection.get(name)
    if existing is not None and not isinstance(existing, list):
        raise ContractError(
            f"set operation on scalar field {name!r} (was {existing!r})")
    current = list(existing or [])
    for item in op.get("add", []):
        if item not in current:
            current.append(item)
    for item in op.get("remove", []):
        if item in current:
            current.remove(item)
    projection[name] = current


def fold_with_provenance(entries: list[dict]) -> dict:
    """Like fold(), but returns {field: {"value": …, "entry": <entry>}} where
    `entry` is the LAST entry that contributed to that field. Scalars: the
    last writer. Sets: the last entry that added or removed a member. The one
    place /doc/{id}'s per-field provenance and the catalogue row's coarse `by`
    are computed — never reimplemented elsewhere."""
    values: dict = {}
    contributor: dict = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SidecarError(f"log entry is not a mapping: {entry!r}")
        fields = entry.get("fields", {})
        if fields is None:
            raise SidecarError(f"entry {entry.get('id', '?')!r} has fields: null")
        for name, value in fields.items():
            if isinstance(value, dict) and ("add" in value or "remove" in value):
                _apply_set(values, name, value)
            elif isinstance(value, list):
                _apply_set(values, name, {"add": value})
            else:
                values[name] = value
            contributor[name] = entry
    return {name: {"value": values[name], "entry": contributor[name]}
            for name in values}
