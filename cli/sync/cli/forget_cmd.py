"""mo sync forget <folder> — remove a sync declaration."""
from __future__ import annotations

import sys
from pathlib import Path

from cli.sync.cli.resolve import compute_declaration_path, resolve_infrastructure
from cli.sync.errors import MouiSyncError


def run(corpus_root: Path, args: list):
    """Remove the sync declaration for a folder. Leaves files alone."""
    if not args:
        print("Usage: mo sync forget <folder>")
        sys.exit(1)

    try:
        infrastructure_path = resolve_infrastructure(args)
    except MouiSyncError as exc:
        print(str(exc))
        sys.exit(1)

    folder_name = args[0]
    infra_parent = infrastructure_path.parent
    folder_path = (infra_parent / folder_name).resolve()

    try:
        decl_path = compute_declaration_path(infrastructure_path, folder_path)
    except MouiSyncError as exc:
        print(str(exc))
        sys.exit(1)

    if not decl_path.exists():
        print(f"No sync declaration for '{folder_name}' at {decl_path}")
        sys.exit(1)

    decl_path.unlink()
    print(f"Removed {decl_path}")
    print(f"Files in {folder_path} are untouched.")

    # Notify daemon
    from cli.sync.cli.init_cmd import _notify_daemon
    _notify_daemon()
