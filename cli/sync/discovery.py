"""Scan infrastructure/syncs/ for sync declarations."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from cli.sync.config import SyncDeclaration, load_sync_declaration
from cli.sync.errors import InfrastructureNotFoundError

logger = logging.getLogger("moui.sync.discovery")


@dataclass
class ResolvedFolder:
    declaration_path: Path
    declaration: SyncDeclaration
    folder_path: Path  # absolute resolved target


def discover_declarations(infrastructure_path: Path) -> list[ResolvedFolder]:
    """Scan infrastructure/syncs/ and return validated, resolved declarations.

    Declarations whose target folder doesn't exist on disk are skipped with a warning.
    """
    if not infrastructure_path.exists():
        raise InfrastructureNotFoundError(str(infrastructure_path))

    syncs_dir = infrastructure_path / "syncs"
    if not syncs_dir.exists():
        return []

    results: list[ResolvedFolder] = []

    for yaml_path in sorted(syncs_dir.rglob("*.yaml")):
        try:
            decl = load_sync_declaration(yaml_path)
        except Exception as exc:
            logger.warning("skipping %s: %s", yaml_path, exc)
            continue

        # target is relative to the yaml file's parent directory
        resolved_target = (yaml_path.parent / decl.target).resolve()

        if not resolved_target.exists():
            logger.warning(
                "target folder missing for %s: %s", yaml_path.name, resolved_target
            )
            continue

        results.append(ResolvedFolder(
            declaration_path=yaml_path,
            declaration=decl,
            folder_path=resolved_target,
        ))

    return results
