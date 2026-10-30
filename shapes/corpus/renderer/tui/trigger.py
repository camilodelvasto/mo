# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The live trigger — what calls the catalogue's refetch() seam. Pluggable: a
TimerTrigger (a clock) now, an SseTrigger (a push) after the in-process SSE
spike. The seam and the refetch path are identical between them; only what
decides WHEN to refetch differs."""


class TimerTrigger:
    """A clock. Re-fetches the bounded current page + counts on an interval —
    the simplest trigger, enough to prove the live loop."""

    def __init__(self, interval: float = 1.5):
        self.interval = interval

    def start(self, screen) -> None:
        screen.set_interval(self.interval, lambda: screen.refetch("all"))


class SseTrigger:
    """A push. Subscribes to /events and re-fetches the affected row per change.
    The granular path: refetch(doc_id), not the whole page."""

    def start(self, screen) -> None:
        screen.run_worker(self._loop(screen), exclusive=False)

    async def _loop(self, screen) -> None:
        async for change in screen.client.events():
            await screen.refetch(change["doc_id"])
