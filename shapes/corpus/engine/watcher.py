# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Watch the corpus folder by polling ticks. Settle = size stable across two
ticks. Emits reactions for dropbox/, inbox/, and flow.yaml changes.
meta.yaml integrity is sidecar.read_verified's job, not an event source."""
import fnmatch
import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Event:
    kind: str                  # dropped | assert | order | flow-changed
    path: Path
    entrypoint: dict | None = None


class Watcher:
    def __init__(self, corpus_dir: Path, entrypoints: list[dict]):
        self.corpus_dir = corpus_dir
        self.entrypoints = entrypoints
        self._sizes: dict[Path, int] = {}      # last seen size per pending drop
        self._seen_asserts: set[Path] = set()
        self._seen_orders: set[Path] = set()
        self._flow_hash = self._hash_flow()

    def tick(self) -> list[Event]:
        events: list[Event] = []
        events += self._scan_dropboxes()
        events += self._scan_inbox()
        events += self._scan_orders()
        events += self._check_flow()
        return events

    def _scan_dropboxes(self) -> list[Event]:
        events = []
        # prune vanished pending files: a stale size entry would let a new
        # file at the same path bypass settle on its first tick
        self._sizes = {p: s for p, s in self._sizes.items() if p.exists()}
        for entrypoint in self.entrypoints:
            area = self.corpus_dir / entrypoint["area"]
            if not area.is_dir():
                continue
            for f in sorted(area.iterdir()):
                if not f.is_file() or f.name.startswith("."):
                    continue
                pattern = entrypoint.get("pattern")
                if pattern is not None and not fnmatch.fnmatch(f.name, pattern):
                    continue
                size = f.stat().st_size
                if self._sizes.get(f) == size:
                    del self._sizes[f]
                    events.append(Event("dropped", f, entrypoint))
                else:
                    self._sizes[f] = size
        return events

    def _scan_inbox(self) -> list[Event]:
        events = []
        inbox = self.corpus_dir / "inbox"
        # prune consumed asserts: a re-dropped file at an already-seen path
        # must fire again, never sit silently ignored
        self._seen_asserts = {p for p in self._seen_asserts if p.exists()}
        if inbox.is_dir():
            for f in sorted(inbox.glob("*.assert.yaml")):
                if f not in self._seen_asserts:
                    self._seen_asserts.add(f)
                    events.append(Event("assert", f))
        return events

    def _scan_orders(self) -> list[Event]:
        events = []
        inbox = self.corpus_dir / "inbox"
        # prune consumed orders: a re-dropped file at an already-seen path
        # must fire again, never sit silently ignored
        self._seen_orders = {p for p in self._seen_orders if p.exists()}
        if inbox.is_dir():
            for f in sorted(inbox.glob("*.order.yaml")):
                if f not in self._seen_orders:
                    self._seen_orders.add(f)
                    events.append(Event("order", f))
        return events

    def _check_flow(self) -> list[Event]:
        current = self._hash_flow()
        if current != self._flow_hash:
            self._flow_hash = current
            return [Event("flow-changed", self.corpus_dir / "flow.yaml")]
        return []

    def _hash_flow(self) -> str:
        path = self.corpus_dir / "flow.yaml"
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
