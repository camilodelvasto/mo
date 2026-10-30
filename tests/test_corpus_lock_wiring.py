# tests/test_corpus_lock_wiring.py
import os

import pytest
from fastapi.testclient import TestClient

from shapes.corpus.service import locks
from shapes.corpus.service.app import create_app
from tests.test_corpus_service_reads import _corpus


def test_status_reports_engine_and_service_liveness(tmp_path):
    corpus = _corpus(tmp_path)
    # an engine lock with a dead pid → engine reported down
    locks._write(corpus / "engine.lock",
                 {"pid": 999999, "host": locks.HOST, "started": "t"})
    body = TestClient(create_app(corpus)).get("/status").json()
    assert body["engine"] is False
    assert body["service"] is False        # no service.lock yet


def test_watch_refuses_when_engine_lock_is_live(tmp_path):
    corpus = _corpus(tmp_path)
    (corpus / "working").mkdir()
    # pretend a live engine already holds the lock (our own pid is alive)
    locks._write(corpus / "engine.lock",
                 {"pid": os.getpid(), "host": locks.HOST, "started": "t"})
    from shapes.corpus.commands import watch
    with pytest.raises(SystemExit):
        watch.run(tmp_path, "corpus", [str(corpus)])
