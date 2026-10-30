# tests/test_sync_corpus_snapshot.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path
from cli.sync.corpus import snapshot


def _corpus(tmp_path):
    c = tmp_path / "corpus-src"
    (c / "corpus").mkdir(parents=True)
    (c / "index").mkdir()
    (c / "derived").mkdir()                      # runtime — must be excluded
    (c / "working").mkdir()                      # transient — must be excluded
    (c / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\nask: ./ask.yaml\n")
    (c / "flow.yaml").write_text("id: c\n")
    (c / "ask.yaml").write_text("id: c-ask\n")
    (c / "corpus" / "doc").mkdir()
    (c / "corpus" / "doc" / "meta.yaml").write_text("doc_id: doc\n")
    (c / "index" / "corpus.db").write_bytes(b"\x00idx")
    (c / "derived" / "catalogue.sqlite").write_bytes(b"runtime")
    (c / ".service.lock").write_text("{}")
    return c


def test_build_snapshot_raises_on_missing_corpus_yaml(tmp_path):
    src = tmp_path / "no-corpus"
    src.mkdir()
    (src / "flow.yaml").write_text("id: x\n")   # has other files, just no corpus.yaml
    import pytest
    with pytest.raises(FileNotFoundError, match="missing corpus.yaml"):
        snapshot.build_snapshot(src, tmp_path / "dest")


def test_snapshot_excludes_runtime(tmp_path):
    src = _corpus(tmp_path); dest = tmp_path / "snap"
    snapshot.build_snapshot(src, dest)
    names = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert "corpus.yaml" in names and "flow.yaml" in names and "ask.yaml" in names
    assert "corpus/doc/meta.yaml" in names and "index/corpus.db" in names
    assert not any(n.startswith("derived/") for n in names)
    assert not any(n.startswith("working/") for n in names)
    assert ".service.lock" not in names


def test_canonical_digest_is_reproducible(tmp_path):
    src = _corpus(tmp_path)
    a = tmp_path / "a"; b = tmp_path / "b"
    snapshot.build_snapshot(src, a); snapshot.build_snapshot(src, b)
    assert snapshot.canonical_digest(a) == snapshot.canonical_digest(b)   # same content → same id


def test_canonical_digest_changes_with_content(tmp_path):
    src = _corpus(tmp_path); a = tmp_path / "a"
    snapshot.build_snapshot(src, a); d1 = snapshot.canonical_digest(a)
    (src / "corpus" / "doc" / "meta.yaml").write_text("doc_id: doc\nchanged: true\n")
    b = tmp_path / "b"; snapshot.build_snapshot(src, b)
    assert snapshot.canonical_digest(b) != d1


def test_version_id_is_pure(tmp_path):
    assert snapshot.version_id("abcdef0123456789ff", now="20260621-120000") \
        == "20260621-120000-abcdef0123456789"


def test_snapshot_drops_macos_cruft(tmp_path):
    # macOS .DS_Store / ._* must never enter the snapshot — they'd ride into the
    # corpus and (with the ship's COPYFILE_DISABLE) the digest must stay canonical.
    src = _corpus(tmp_path)
    (src / "corpus" / ".DS_Store").write_bytes(b"cruft")
    (src / "corpus" / "._hidden").write_bytes(b"appledouble")
    dest = tmp_path / "snap-clean"
    snapshot.build_snapshot(src, dest)
    names = {p.name for p in dest.rglob("*")}
    assert ".DS_Store" not in names
    assert "._hidden" not in names
    assert "meta.yaml" in names                 # real content still copied
