# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import os
import subprocess
from pathlib import Path

import pytest
from cli.sync.corpus import _volume_op as vop


def _vol(tmp_path):
    v = tmp_path / "vol"; (v / "versions" / "v1").mkdir(parents=True)
    (v / "versions" / "v2").mkdir()
    os.symlink("versions/v1", v / "current")
    return v


def test_flip_advances_current_and_sets_previous(tmp_path):
    v = _vol(tmp_path); vop.flip(v, "v2")
    assert os.readlink(v / "current") == "versions/v2"
    assert os.readlink(v / "previous") == "versions/v1"      # previous = pre-flip current


def test_flip_replaces_the_symlink_not_follows_into_dir(tmp_path):
    # current → a real dir; the replace must swap the symlink, never move tmp INTO v1/
    v = _vol(tmp_path); vop.flip(v, "v2")
    assert (v / "current").is_symlink()
    assert not (v / "versions" / "v1" / "current").exists()


def test_rollback_restores_previous(tmp_path):
    v = _vol(tmp_path); vop.flip(v, "v2"); vop.rollback(v)
    assert os.readlink(v / "current") == "versions/v1"


def test_prune_keeps_current_previous_and_depth(tmp_path):
    v = _vol(tmp_path)
    for n in ("v3", "v4"): (v / "versions" / n).mkdir()
    vop.flip(v, "v2")                                        # current=v2, previous=v1
    vop.prune(v, keep=1)
    names = {p.name for p in (v / "versions").iterdir()}
    assert "v2" in names and "v1" in names                  # current + previous never pruned


def test_migration_script_creates_versions_and_current(tmp_path):
    base = tmp_path / "corpus"; d = base / "acme-notes"; d.mkdir(parents=True)
    (d / "corpus.yaml").write_text("id: p\n"); (d / "index").mkdir()
    script = Path(__file__).resolve().parents[1] / "infrastructure/corpus-server/migrate-volume.sh"
    if not script.is_file():
        pytest.skip("migrate-volume.sh not present (gitignored, present only on a working checkout)")
    subprocess.run(["bash", str(script), str(base), "acme-notes", "v0"], check=True)
    assert os.readlink(d / "current") == "versions/v0"
    assert (d / "versions" / "v0" / "corpus.yaml").exists()
    assert (d / "versions" / "v0" / "index").is_dir()
