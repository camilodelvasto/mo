# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import importlib, pytest
from pathlib import Path


def test_corpus_cmd_requires_two_args(monkeypatch):
    m = importlib.import_module("cli.sync.cli.corpus_cmd")
    with pytest.raises(SystemExit):
        m.run(Path("/root"), ["only-one"])


def test_corpus_cmd_calls_sync_run(monkeypatch):
    m = importlib.import_module("cli.sync.cli.corpus_cmd")
    seen = {}
    monkeypatch.setattr(m.sync, "run",
                        lambda root, t, e, *, now: seen.update(t=t, e=e, now=now))
    m.run(Path("/root"), ["corpus-server/acme", "prod"])
    assert seen["t"] == "corpus-server/acme" and seen["e"] == "prod" and seen["now"]


def test_sync_dispatch_registers_corpus_and_rollback():
    sync_mod = importlib.import_module("cli.commands.sync")
    assert sync_mod.SUBCOMMANDS["corpus"] == "cli.sync.cli.corpus_cmd"
    assert sync_mod.SUBCOMMANDS["rollback"] == "cli.sync.cli.rollback_cmd"
