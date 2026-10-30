# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Sheets CLI utilities — sheet resolution, port binding, discovery."""
import socket
import sys
from pathlib import Path

import yaml


DEFAULT_PORT = 4300
MAX_PORT_ATTEMPTS = 10


def resolve_sheet(path_or_name: str, corpus_root: Path) -> Path:
    """Resolve a sheet directory from a path or content directory name.

    Tries in order:
    1. path_or_name as absolute path (if it's a dir with sheet.yaml)
    2. corpus_root / path_or_name (if it's a relative dir with sheet.yaml)
    3. corpus_root / "content" / path_or_name (shorthand for content sheets)

    Exits with error if nothing resolves.
    """
    candidate = Path(path_or_name)
    if not candidate.is_absolute():
        candidate = corpus_root / path_or_name

    if candidate.is_dir() and (candidate / "sheet.yaml").exists():
        return candidate.resolve()

    # Try content/ shorthand
    content_candidate = corpus_root / "content" / path_or_name
    if content_candidate.is_dir() and (content_candidate / "sheet.yaml").exists():
        return content_candidate.resolve()

    print(
        f"Error: '{path_or_name}' is not a sheet directory (no sheet.yaml found)",
        file=sys.stderr,
    )
    sys.exit(1)


def read_sheet_port(sheet_dir: Path) -> int | None:
    """Read the declared port from sheet.yaml. Returns None if not declared."""
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    return sheet.get("port")


def bind_port(declared_port: int | None, default_start: int = DEFAULT_PORT) -> int:
    """Bind to declared port (throws on collision) or find free port in default range."""
    if declared_port is not None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", declared_port))
                return declared_port
        except OSError:
            print(
                f"Error: port {declared_port} is in use.",
                file=sys.stderr,
            )
            sys.exit(1)

    for offset in range(MAX_PORT_ATTEMPTS):
        port = default_start + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue

    raise RuntimeError(
        f"No free port found in range {default_start}-{default_start + MAX_PORT_ATTEMPTS - 1}"
    )


def discover_sheets(corpus_root: Path) -> list[dict]:
    """Walk content/ to find all sheet.yaml files."""
    sheets = []
    content_dir = corpus_root / "content"
    if not content_dir.exists():
        return sheets

    for child in sorted(content_dir.iterdir()):
        sheet_yaml = child / "sheet.yaml"
        if child.is_dir() and sheet_yaml.exists():
            sheet = yaml.safe_load(sheet_yaml.read_text())
            sheets.append({
                "name": child.name,
                "path": str(child),
                "port": sheet.get("port"),
                "title": sheet.get("title", child.name),
            })
    return sheets
