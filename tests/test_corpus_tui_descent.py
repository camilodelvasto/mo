# tests/test_corpus_tui_descent.py
import pytest

from shapes.corpus.renderer.tui import keymap
from shapes.corpus.renderer.tui.app import CatalogueApp
from shapes.corpus.renderer.tui.document import DocumentScreen
from tests.test_corpus_tui_catalogue import _FakeClient


def _app(client):
    bindings = keymap.load_bindings(
        keymap.Path("shapes/corpus/renderer/tui/bindings.default.yaml"),
        keymap.Path("."), keymap.READ_CAPABILITIES)
    return CatalogueApp(client=client, declared=["doc_type", "consent", "tags"],
                        bindings=bindings)


@pytest.mark.asyncio
async def test_enter_pushes_document_screen_for_the_row():
    client = _FakeClient()
    client.doc = lambda doc_id: _doc_payload()
    async with _app(client).run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DocumentScreen)
        assert pilot.app.screen.doc_id == "3f9a21abcdef"


@pytest.mark.asyncio
async def test_esc_returns_to_the_catalogue_with_state_intact():
    client = _FakeClient()
    client.doc = lambda doc_id: _doc_payload()
    async with _app(client).run_test() as pilot:
        await pilot.pause()
        await pilot.press("2")                       # switch to the pending lens
        assert client.last_catalogue["lens"] == "pending"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DocumentScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, DocumentScreen)   # back on catalogue
        from textual.widgets import DataTable
        assert pilot.app.query_one("#table", DataTable)            # catalogue intact


async def _doc_payload():
    return {"doc_id": "3f9a21abcdef", "status": "complete",
            "flow": {"id": "corpus-prep", "version": 4, "hash": "sha256:8c"},
            "fields": {"doc_type": {"value": "interview",
                "provenance": {"stage": "classify", "by": "model"}}}}
