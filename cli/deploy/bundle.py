# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Stage the full build context the box's Dockerfiles need, mirroring the box
root, ready for box.ship. "Pure logic" is the EXCLUSION test, not a size claim:
include everything the build COPYs (serve.Dockerfile: pyproject/moui.json/cli/
shapes/bin; gate.Dockerfile: corpus_server; plus infrastructure/corpus-server),
exclude every datum and secret (corpus, secrets, capabilities.yaml, access.csv,
ledger). The include-list IS the exclusion test made executable — a data/secret
path can't ride by accident because only the listed logic is copied. Built from
the working tree, so the bundle is the deployed commit: reproducible, inspectable."""
import shutil
from pathlib import Path

INCLUDE = (
    "pyproject.toml", "moui.json",
    "cli", "shapes", "bin", "corpus_server",
    "infrastructure/corpus-server",
)

# Inside an included dir but never shipped: dev/ holds a local access.csv,
# attest.secret, ledgers and logs. Nothing on the box reads it (the compose
# override there is dev-only).
EXCLUDE = ("infrastructure/corpus-server/dev",)

_PRUNE = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _ignore_under(corpus_root: Path):
    excluded = {corpus_root / e for e in EXCLUDE}

    def _ignore(dir_, names):
        return [n for n in names if n in _PRUNE or Path(dir_) / n in excluded]
    return _ignore


def stage_bundle(corpus_root: Path, dotenv: str, gate_yaml: str,
                 stage_dir: Path) -> Path:
    stage_dir.mkdir(parents=True, exist_ok=True)
    for item in INCLUDE:
        src = corpus_root / item
        dst = stage_dir / item
        if not src.exists():
            raise FileNotFoundError(f"build context missing: {src}")
        if src.is_dir():
            shutil.copytree(src, dst, ignore=_ignore_under(corpus_root), dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    # capabilities.yaml is NOT shipped in the bundle: the tar replaces the file's
    # inode each deploy, and the serve single-file-mounts it — so a tarred copy goes
    # stale until the container is recreated. It is placed via box.put_file (cat >,
    # in-place truncate) instead, which the live mount sees. Drop any per-instance
    # copy the infrastructure sweep pulled in so none rides the bundle.
    for stray in (stage_dir / "infrastructure" / "corpus-server").glob("*/capabilities.yaml"):
        stray.unlink()
    box_config = stage_dir / "box-config"
    box_config.mkdir(parents=True, exist_ok=True)
    (box_config / ".env").write_text(dotenv)
    (box_config / "gate.yaml").write_text(gate_yaml)
    return stage_dir
