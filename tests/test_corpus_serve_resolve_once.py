# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from pathlib import Path
from shapes.corpus.commands._read import resolve_corpus
from shapes.corpus.engine.errors import CorpusError


def test_resolve_corpus_refuses_dangling_symlink(tmp_path):
    target = tmp_path / "versions" / "v1"; target.mkdir(parents=True)
    (target / "corpus.yaml").write_text("id: c\n")
    current = tmp_path / "current"; current.symlink_to(target)
    # resolves and serves
    assert resolve_corpus([str(current)]) == target.resolve()
    # now dangle it
    import shutil; shutil.rmtree(target)
    with pytest.raises(CorpusError, match="missing or a dangling symlink"):
        resolve_corpus([str(current)])


def test_resolve_corpus_returns_realpath_not_symlink(tmp_path):
    target = tmp_path / "versions" / "v1"; target.mkdir(parents=True)
    (target / "corpus.yaml").write_text("id: c\n")
    current = tmp_path / "current"; current.symlink_to(target)
    got = resolve_corpus([str(current)])
    assert got == target.resolve()           # the realpath, not the symlink path
    assert "current" not in str(got)
