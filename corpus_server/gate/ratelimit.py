# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Per-IP edge rate limit + repeated-401 block, in the gate because Caddy core
has no limiter without a custom build. In-memory since boot; a restart clears
the block tally, which is acceptable — entropy, not the block, keeps the code
space unsearchable."""
from collections import defaultdict, deque
from datetime import datetime


def parse_duration(s) -> int:
    s = str(s).strip()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("s"):
        return int(s[:-1])
    return int(s)


class RateLimiter:
    def __init__(self, per_minute: int, block_after: int, block_for):
        self.per_minute = per_minute
        self.block_after = block_after
        self.block_for = parse_duration(block_for)
        self._hits: dict[str, deque] = defaultdict(deque)
        self._401s: dict[str, deque] = defaultdict(deque)
        self._blocked: dict[str, float] = {}

    def check(self, ip: str, now: datetime) -> tuple[bool, int]:
        t = now.timestamp()
        unblock = self._blocked.get(ip)
        if unblock is not None:
            if t < unblock:
                return False, max(1, int(unblock - t))
            del self._blocked[ip]
        dq = self._hits[ip]
        while dq and dq[0] <= t - 60:
            dq.popleft()
        if len(dq) >= self.per_minute:
            return False, max(1, int(dq[0] + 60 - t))
        dq.append(t)
        return True, 0

    def record_401(self, ip: str, now: datetime) -> None:
        t = now.timestamp()
        dq = self._401s[ip]
        while dq and dq[0] <= t - 60:
            dq.popleft()
        dq.append(t)
        if len(dq) >= self.block_after:
            self._blocked[ip] = t + self.block_for
