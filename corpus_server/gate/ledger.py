# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The gate's append-only record. Rolls per window so the boot replay is
window-scoped and growth is bounded: ledger.jsonl -> ledger-2026-06.jsonl."""
import json
from datetime import datetime
from pathlib import Path


def window_suffix(window: str, now: datetime) -> str:
    if window == "month":
        return now.strftime("%Y-%m")
    if window == "lifetime":
        return "lifetime"
    raise ValueError(f"unknown window {window!r}")


def window_path(base: Path, window: str, now: datetime) -> Path:
    base = Path(base)
    stem = base.with_suffix("")
    return stem.parent / f"{stem.name}-{window_suffix(window, now)}{base.suffix}"


def append(path: Path, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_ask_events(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("event") == "ask":
            out.append(rec)
    return out
