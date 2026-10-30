"""CLI entry point for `mo sync <subcommand>`. Dispatches to subcommand modules."""

import importlib
import sys
from pathlib import Path

SUBCOMMANDS = {
    "init": "cli.sync.cli.init_cmd",
    "status": "cli.sync.cli.status_cmd",
    "pull": "cli.sync.cli.pull_cmd",
    "logs": "cli.sync.cli.logs_cmd",
    "recipients": "cli.sync.cli.recipients_cmd",
    "rescan": "cli.sync.cli.rescan_cmd",
    "daemon": "cli.sync.cli.daemon_cmd",
    "forget": "cli.sync.cli.forget_cmd",
    "corpus": "cli.sync.cli.corpus_cmd",
    "rollback": "cli.sync.cli.rollback_cmd",
}


def _print_usage():
    print("Usage: mo sync <command> [args...]")
    print()
    print("Commands:")
    print("  init <folder>           Set up sync for a folder")
    print("  <folder>                Sync a folder now")
    print("  pull [folder]           Pull from remote")
    print("  status                  Show sync state")
    print("  logs [--follow]         View sync log")
    print("  recipients <folder>     Manage folder recipients")
    print("  rescan                  Re-scan declarations")
    print("  forget <folder>         Remove sync declaration")
    print("  daemon start|stop       Manage sync daemon")


def run(corpus_root: Path, args: list):
    if not args:
        _print_usage()
        sys.exit(1)

    subcommand = args[0]
    sub_args = args[1:]

    if subcommand in SUBCOMMANDS:
        module = importlib.import_module(SUBCOMMANDS[subcommand])
        module.run(corpus_root, sub_args)
    else:
        # Treat first arg as a folder path: mo sync <folder>
        module = importlib.import_module("cli.sync.cli.sync_cmd")
        module.run(corpus_root, args)
