"""Resolve infrastructure paths and folder arguments for sync CLI commands.

Shared by all CLI commands. No fallbacks, no defaults, no sys.exit.
Raises domain errors that CLI entry points catch and present.
"""
from __future__ import annotations

from pathlib import Path

from cli.sync.config import load_sync_declaration
from cli.sync.errors import (
    ConfigValidationError,
    InfrastructureNotFoundError,
)


def find_infrastructure(start_path: Path) -> Path:
    """Walk up from start_path to find infrastructure/remotes.yaml.

    Raises InfrastructureNotFoundError if not found.
    """
    current = start_path.resolve()
    while current != current.parent:
        candidate = current / "infrastructure" / "remotes.yaml"
        if candidate.exists():
            return current / "infrastructure"
        current = current.parent
    raise InfrastructureNotFoundError(
        f"no infrastructure/remotes.yaml found above {start_path}"
    )


def compute_declaration_path(infrastructure_path: Path, folder_path: Path) -> Path:
    """Compute infrastructure/syncs/<mirror>.yaml for the given folder.

    Raises ConfigValidationError if the folder is outside the infrastructure tree.
    """
    infra_parent = infrastructure_path.parent
    try:
        relative = folder_path.resolve().relative_to(infra_parent.resolve())
    except ValueError:
        raise ConfigValidationError(
            f"folder must be in the same directory tree as infrastructure/.\n"
            f"  infrastructure: {infrastructure_path}\n"
            f"  folder: {folder_path}"
        )
    return infrastructure_path / "syncs" / (str(relative) + ".yaml")


def resolve_infrastructure(args: list) -> Path:
    """Extract --infrastructure from args, or find it by walking up from cwd.

    Raises InfrastructureNotFoundError if not found.
    """
    if "--infrastructure" in args:
        idx = args.index("--infrastructure")
        if idx + 1 < len(args):
            path = Path(args[idx + 1]).resolve()
            if not (path / "remotes.yaml").exists():
                raise InfrastructureNotFoundError(
                    f"no remotes.yaml at {path}"
                )
            return path
    return find_infrastructure(Path.cwd())


def resolve_folder(args: list) -> Path:
    """Resolve folder arg to an absolute target path via sync declarations.

    The folder name is relative to the workspace root (infrastructure's parent).
    Reads the declaration to get the canonical target path.

    Raises domain errors on any failure.
    """
    folder_name = args[0]
    infrastructure_path = resolve_infrastructure(args)

    infra_parent = infrastructure_path.parent
    folder_path = (infra_parent / folder_name).resolve()

    decl_path = compute_declaration_path(infrastructure_path, folder_path)
    if not decl_path.exists():
        raise ConfigValidationError(
            f"no sync declaration for '{folder_name}' at {decl_path}"
        )

    decl = load_sync_declaration(decl_path)
    resolved = (decl_path.parent / decl.target).resolve()

    if not resolved.exists():
        raise ConfigValidationError(
            f"target folder does not exist: {resolved}"
        )

    return resolved
