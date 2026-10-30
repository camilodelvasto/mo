# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""What a deploy adapter's deploy() returns — the contract with the deploy rail.

Live: the URL serves this release. Staged: the release is on the remote but the
URL does not serve it yet; reason says why and what moves it live. Any other
return value is a broken adapter and the rail throws.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Live:
    url: str


@dataclass(frozen=True)
class Staged:
    url: str
    reason: str
