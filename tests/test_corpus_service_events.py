# tests/test_corpus_service_events.py
import asyncio

from shapes.corpus.service.app import create_app
from tests.test_corpus_service_reads import _corpus, _pair


def test_poll_once_fans_changes_out_to_subscribers(tmp_path):
    corpus = _corpus(tmp_path)
    app = create_app(corpus)
    q: asyncio.Queue = asyncio.Queue()
    app.state.subscribers.add(q)               # stand in for an /events listener
    # a new doc settles into the tree after the subscriber is registered
    _pair(corpus, "corpus", "aaaaaaaaaaaa", [], "complete")
    app.state.poll_once()                      # drive the poller deterministically
    change = q.get_nowait()
    assert change["doc_id"] == "aaaaaaaaaaaa"
    assert change["change"] in ("sidecar", "moved")


def test_poll_once_with_no_change_pushes_nothing(tmp_path):
    corpus = _corpus(tmp_path)
    app = create_app(corpus)
    q: asyncio.Queue = asyncio.Queue()
    app.state.subscribers.add(q)
    app.state.poll_once()
    assert q.empty()
