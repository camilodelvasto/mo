# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""In-memory request counts, keyed by identity, seeded window-scoped from the
ledger. The check is a dict lookup against the role's ceiling."""
from collections import defaultdict


class Counter:
    def __init__(self, roles: dict):
        self.caps = {r: spec["cap"] for r, spec in roles.items()}
        self._n: dict[str, int] = defaultdict(int)

    def seed(self, ask_events) -> None:
        for ev in ask_events:
            self._n[ev["id"]] += 1

    def under_cap(self, identity: str, role: str) -> bool:
        if role not in self.caps:
            raise ValueError(f"unknown role {role!r}")
        return self._n[identity] < self.caps[role]

    def increment(self, identity: str) -> None:
        self._n[identity] += 1
