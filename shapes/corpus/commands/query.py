# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo corpus query <save|list> <path> ... — persist and list saved queries.
`save` reads the result record on stdin (unless --definition-only) and takes the
definition as flags; the CLI stamps `saved`. The engine owns the file format."""
import json
import sys
from datetime import datetime
from pathlib import Path

from shapes.corpus.access import queries
from shapes.corpus.commands._access_cli import parse_grounding
from shapes.corpus.commands._read import resolve_corpus

_REQUIRED = ("ask", "question", "grounding", "mode")


def run(corpus_root: Path, instance: str, args: list) -> None:
    if not args:
        raise SystemExit("usage: mo corpus query <save|list> <path> ...")
    sub, rest = args[0], args[1:]
    corpus = resolve_corpus(rest)                  # rest[0] is the path
    if sub == "save":
        _save(corpus, rest[1:])
    elif sub == "list":
        _list(corpus, rest[1:])
    else:
        raise SystemExit(f"unknown query subcommand {sub!r} (use save | list)")


def _save(corpus: Path, args: list) -> None:
    if not args:
        raise SystemExit("usage: mo corpus query save <path> <name> --ask A "
                         "--question Q --grounding G --mode M [--where E] [--definition-only]")
    name, flags = args[0], _parse_save_flags(args[1:])
    for req in _REQUIRED:
        if req not in flags:
            raise SystemExit(f"query save: missing required --{req}")
    definition = {
        "ask": flags["ask"], "question": flags["question"],
        "grounding": parse_grounding(flags["grounding"]), "mode": flags["mode"],
        "where": flags.get("where"),
        "saved": datetime.now().isoformat(timespec="seconds"),
    }
    record = None if flags.get("definition_only") else json.loads(sys.stdin.read())
    print(queries.save_query(corpus, name, definition, record))


def _parse_save_flags(args: list) -> dict:
    flags: dict = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--definition-only":
            flags["definition_only"] = True; i += 1
        elif a in ("--ask", "--question", "--grounding", "--mode", "--where"):
            if i + 1 >= len(args):
                raise SystemExit(f"query save: {a} needs a value")
            flags[a[2:]] = args[i + 1]; i += 2
        else:
            raise SystemExit(f"query save: unknown flag {a!r}")
    return flags


def _list(corpus: Path, args: list) -> None:
    items = queries.list_queries(corpus)
    if "--json" in args:
        print(json.dumps(items, ensure_ascii=False))
        return
    for it in items:
        print(f"{it['name']}  [{it.get('ask')}]  {it.get('saved', '')}  {it.get('question', '')}")
