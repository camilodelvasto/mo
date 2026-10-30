# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus order <corpus> <doc_id> reprocess [--from <stage>] | retire —
write one order file into inbox/. The engine validates and acts on its own
clock; this command only materializes the file (same path the service uses)."""
import sys
from pathlib import Path

import yaml
from ulid import ULID

from shapes.corpus.commands._read import resolve_corpus

ACTIONS = ("reprocess", "retire")


def run(corpus_root: Path, instance: str, args: list) -> None:
    from_stage = None
    if "--from" in args:
        i = args.index("--from")
        from_stage = args[i + 1]
        args = args[:i] + args[i + 2:]
    positional = [a for a in args if not a.startswith("--")]
    if len(positional) < 3:
        print("usage: mo corpus order <corpus> <doc_id> reprocess [--from <stage>] | retire",
              file=sys.stderr)
        sys.exit(1)
    corpus = resolve_corpus(positional[:1])
    doc_id, action = positional[1], positional[2]
    if action not in ACTIONS:
        print(f"unknown action {action!r}: one of {', '.join(ACTIONS)}", file=sys.stderr)
        sys.exit(1)
    payload = {"doc_id": doc_id, "by": "operator", "action": action}
    if from_stage is not None:
        payload["from"] = from_stage
    inbox = corpus / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    name = f"{ULID()}-{doc_id}.order.yaml"
    (inbox / name).write_text(yaml.safe_dump(payload, sort_keys=False))
    print(f"wrote inbox/{name}")
