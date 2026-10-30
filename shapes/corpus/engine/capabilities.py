# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Load the machine-root capabilities.yaml; resolve names; VERIFY at startup.

A name the flow uses with no binding — or a bound binary missing from the
machine — is a startup error. The engine refuses to watch the corpus and
names what is missing. No silent fallback, no degraded start.
"""
import shutil
from pathlib import Path

import yaml

from shapes.corpus.engine.errors import CapabilityError


def load_table(machine_root: Path) -> dict:
    path = machine_root / "capabilities.yaml"
    if not path.is_file():
        raise CapabilityError(
            f"no binding table at {path} — copy "
            "shapes/corpus/config/capabilities.example.yaml and edit it"
        )
    table = yaml.safe_load(path.read_text())
    if not isinstance(table, dict) or "capabilities" not in table:
        raise CapabilityError(f"{path} has no capabilities: block")
    return table


def names_used(flow: dict) -> set[str]:
    names: set[str] = set()
    for stage in flow.get("pipeline", []):
        uses = stage["uses"]
        if isinstance(uses, str):
            names.add(uses)
        else:
            names.update(uses["routes"].values())
    return names


def verify(flow: dict, table: dict, builtin_names: set[str]) -> None:
    bound = table.get("capabilities", {})
    problems = []
    for name in sorted(names_used(flow)):
        if name.startswith("engine."):
            if name not in builtin_names:
                problems.append(f"{name}: not a builtin this engine ships")
            continue
        entry = bound.get(name)
        if entry is None:
            problems.append(f"{name}: not bound in capabilities.yaml")
            continue
        binary = entry["run"][0]
        if shutil.which(binary) is None:
            problems.append(f"{name}: binary not on this machine: {binary}")
        if entry.get("emits") == "transcript" and "${output}" not in entry["run"]:
            problems.append(f"{name}: emits: transcript but run: has no ${{output}}")
    if problems:
        raise CapabilityError(
            "refusing to watch this corpus:\n  " + "\n  ".join(problems)
        )


def resolve(name: str, table: dict) -> dict:
    bound = table["capabilities"]
    entry = bound.get(name)
    if entry is None:
        raise CapabilityError(f"unbound capability: {name}")
    return entry
