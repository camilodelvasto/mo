# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The condition language (stage when: and flow rules:) and rule evaluation.

Grammar, deliberately tiny:
    fields.<name> == <word>
    fields.<name> != <word>
    fields.<name> in [<word>, <word>, ...]
Anything else is a ContractError — no eval(), no silent false.
"""
import re

from shapes.corpus.engine.errors import ContractError

_EQ = re.compile(r"^fields\.([A-Za-z_][\w-]*)\s*(==|!=)\s*([\w-]+)$")
_IN = re.compile(r"^fields\.([A-Za-z_][\w-]*)\s+in\s+\[([^\]]*)\]$")


def evaluate_condition(expr: str, projection: dict) -> bool:
    expr = expr.strip()
    m = _EQ.match(expr)
    if m:
        name, op, value = m.groups()
        actual = projection.get(name)
        return (actual == value) if op == "==" else (actual is not None and actual != value)
    m = _IN.match(expr)
    if m:
        name, values = m.groups()
        wanted = [v.strip() for v in values.split(",") if v.strip()]
        return projection.get(name) in wanted
    raise ContractError(f"unparseable condition: {expr!r}")


def due_rules(flow: dict, projection: dict) -> list[dict]:
    """Rules whose when: holds, in declaration order."""
    return [rule for rule in flow.get("rules", []) if evaluate_condition(rule["when"], projection)]
