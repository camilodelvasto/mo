# tests/test_corpus_tui_ask_open.py
import pytest

from shapes.corpus.renderer.tui import ask_runner
from shapes.corpus.renderer.tui.app import CatalogueApp
from shapes.corpus.renderer.tui.ask_screen import AskScreen
from tests.test_corpus_tui_catalogue import _FakeClient


def _app(tmp_path):
    return CatalogueApp(client=_FakeClient(), declared=["doc_type", "consent", "tags"],
                        corpus_dir=tmp_path, asks=["find", "answer"])


@pytest.mark.asyncio
async def test_pressing_a_pushes_the_ask_screen(tmp_path, monkeypatch):
    async def _empty(corpus):
        return []
    monkeypatch.setattr(ask_runner, "list_queries", _empty)
    async with _app(tmp_path).run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(pilot.app.screen, AskScreen)
        assert pilot.app.screen.asks == ["find", "answer"]
