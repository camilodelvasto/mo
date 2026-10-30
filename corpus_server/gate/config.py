# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Load and validate the rendered gate.yaml. No fallbacks: a missing key or an
inconsistent reference is a startup error that names what is wrong."""
from pathlib import Path

import yaml

_REQUIRED = ("upstream", "ledger", "exposed_asks", "auth",
             "roles", "default_role", "window", "rate_limit")
_SCHEMES = ("access-code", "none")


def load_gate_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text())
    if not isinstance(cfg, dict):
        raise ValueError(f"{path}: not a mapping")
    for key in _REQUIRED:
        if key not in cfg:
            raise ValueError(f"{path}: missing '{key}'")
    scheme = cfg["auth"].get("scheme")
    if scheme not in _SCHEMES:
        raise ValueError(f"{path}: unknown auth scheme {scheme!r}")
    if scheme == "access-code" and not cfg["auth"].get("access_list"):
        raise ValueError(f"{path}: access-code scheme needs auth.access_list")
    if cfg["default_role"] not in cfg["roles"]:
        raise ValueError(f"{path}: default_role {cfg['default_role']!r} not in roles")
    # Validate inner shape too — the gate reads these keys directly at startup, so
    # a misspelled inner key must fail HERE with a named error, not later as a bare
    # KeyError in create_gate/Counter.
    if not isinstance(cfg["rate_limit"], dict):
        raise ValueError(f"{path}: rate_limit must be a mapping")
    for rk in ("per_minute", "block_after", "block_for"):
        if rk not in cfg["rate_limit"]:
            raise ValueError(f"{path}: rate_limit missing '{rk}'")
    if not isinstance(cfg["roles"], dict) or not cfg["roles"]:
        raise ValueError(f"{path}: roles must be a non-empty mapping")
    for role, spec in cfg["roles"].items():
        if not isinstance(spec, dict) or "cap" not in spec:
            raise ValueError(f"{path}: role {role!r} missing 'cap'")
    return cfg
