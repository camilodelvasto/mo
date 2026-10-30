# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Auth verifiers. Each takes a request's credential and returns an identity +
role, or None for a refusal. The access list is read per request so revocation
is instant — no reload."""
import csv
from pathlib import Path

_BEARER = "Bearer "


def verify_access_code(authorization: str | None, access_list_path: Path,
                       roles: dict) -> tuple[str, str] | None:
    if not authorization or not authorization.startswith(_BEARER):
        return None
    code = authorization[len(_BEARER):].strip()
    if not code:
        return None
    with access_list_path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["code"] == code and row["active"].strip().lower() == "true":
                role = row["role"].strip()
                if role not in roles:
                    raise ValueError(
                        f"access row {row['id']!r} names undefined role {role!r}")
                return row["id"].strip(), role
    return None
