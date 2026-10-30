# tests/test_corpus_locks.py
import os

import pytest

from shapes.corpus.engine.errors import LockError
from shapes.corpus.service import locks


def test_acquire_writes_pid_and_host(tmp_path):
    lock = tmp_path / "engine.lock"
    locks.acquire(lock, {"role": "engine"})
    data = locks.read(lock)
    assert data["pid"] == os.getpid()
    assert data["host"] == locks.HOST
    assert data["role"] == "engine"


def test_second_live_acquire_refuses(tmp_path):
    lock = tmp_path / "engine.lock"
    locks.acquire(lock, {"role": "engine"})
    with pytest.raises(LockError, match="held by live"):
        locks.acquire(lock, {"role": "engine"})


def test_stale_dead_pid_is_reclaimed(tmp_path):
    lock = tmp_path / "engine.lock"
    locks._write(lock, {"pid": 999999, "host": locks.HOST, "started": "t"})
    locks.acquire(lock, {"role": "engine"})       # must reclaim, not raise
    assert locks.read(lock)["pid"] == os.getpid()


def test_foreign_host_refuses(tmp_path):
    lock = tmp_path / "engine.lock"
    locks._write(lock, {"pid": 1, "host": "some-other-host", "started": "t"})
    with pytest.raises(LockError, match="another host"):
        locks.acquire(lock, {"role": "engine"})


def test_liveness_reports_alive_and_absent(tmp_path):
    assert locks.alive(tmp_path / "missing.lock") is False
    lock = tmp_path / "service.lock"
    locks.acquire(lock, {"role": "service", "port": 8787})
    assert locks.alive(lock) is True


def test_lock_path_lives_outside_the_corpus(tmp_path, monkeypatch):
    # the serve must never write into the corpus — a read-only corpus mount is
    # the enforcement of that line. The lock goes to the runtime dir instead.
    monkeypatch.setenv("MOUI_LOCK_DIR", str(tmp_path / "rt"))
    corpus = tmp_path / "c"; corpus.mkdir()
    p = locks.lock_path(corpus, "service.lock")
    assert corpus.resolve() not in p.resolve().parents       # NOT inside the corpus
    assert (tmp_path / "rt").resolve() in p.resolve().parents  # in the runtime dir
    locks.acquire(p, {"role": "service", "port": 8787})
    assert not (corpus / "service.lock").exists()            # corpus untouched
    assert not (corpus / ".service.lock.tmp").exists()


def test_lock_path_keeps_per_corpus_contention(tmp_path, monkeypatch):
    # relocating the lock must not weaken it: same corpus still contends,
    # different corpora don't share a lock.
    monkeypatch.setenv("MOUI_LOCK_DIR", str(tmp_path / "rt"))
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    locks.acquire(locks.lock_path(a, "service.lock"), {"role": "service"})
    with pytest.raises(LockError, match="already running"):
        locks.acquire(locks.lock_path(a, "service.lock"), {"role": "service"})  # SAME corpus → contention
    locks.acquire(locks.lock_path(b, "service.lock"), {"role": "service"})       # DIFFERENT corpus → no contention
