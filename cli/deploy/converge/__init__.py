# cli/deploy/converge/__init__.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The converge-adapter registry — the swap seam. A stack target names its
mechanism (`converge: compose`); resolve() loads cli/deploy/converge/<name>.py.
A second mechanism is a sibling module here; the rail never changes. This is a
SEPARATE registry from the copy adapters (shapes/shared/adapters/*.py) because
the contracts differ: copy is deploy(...)->url, converge is
converge(...)->None — never one signature for both. No fallback: an unknown
mechanism fails loud."""
import importlib


class ConvergeError(Exception):
    pass


def resolve(name: str):
    try:
        mod = importlib.import_module(f"cli.deploy.converge.{name}")
    except ModuleNotFoundError:
        raise ConvergeError(
            f"unknown converge mechanism {name!r} — no "
            f"cli/deploy/converge/{name}.py (declare a known 'converge:' value)")
    if not hasattr(mod, "converge"):
        raise ConvergeError(f"converge adapter {name!r} has no converge()")
    return mod
