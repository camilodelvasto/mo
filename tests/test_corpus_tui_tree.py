# tests/test_corpus_tui_tree.py
import pytest
from textual.widgets import Tree, DataTable
from shapes.corpus.renderer.tui.app import CatalogueApp
from tests.test_corpus_tui_catalogue import _FakeClient


class _FacetClient(_FakeClient):
    async def search(self, q):
        return []

    async def facets(self):
        return {"facets": [
            {"key": "status", "values": [
                {"value": "all", "count": 2}, {"value": "pending", "count": 1},
                {"value": "done", "count": 1}]},
            {"key": "doc_type", "values": [
                {"value": "interview", "count": 1}, {"value": "report", "count": 1}]}]}

    async def catalogue(self, lens="all", where="", field=None, value=None,
                        cursor=0, limit=100):
        self.last = {"lens": lens, "field": field, "value": value}
        return await super().catalogue(lens=lens, where=where, cursor=cursor, limit=limit)


def _app(client):
    return CatalogueApp(client=client, declared=["doc_type", "consent", "tags"])


@pytest.mark.asyncio
async def test_rail_renders_status_first_then_field_facets():
    client = _FacetClient()
    async with _app(client).run_test() as pilot:
        await pilot.pause()
        tree = pilot.app.query_one("#facet-tree", Tree)
        cats = [str(n.label) for n in tree.root.children]
        assert cats[0].startswith("status") or cats[0] == "status"
        assert any("doc_type" in c for c in cats)


@pytest.mark.asyncio
async def test_selecting_a_status_leaf_filters_by_lens():
    client = _FacetClient()
    async with _app(client).run_test() as pilot:
        await pilot.pause()
        tree = pilot.app.query_one("#facet-tree", Tree)
        pending = tree.root.children[0].children[1]        # status > pending
        tree.select_node(pending)
        await pilot.pause()
        assert client.last["lens"] == "pending"


@pytest.mark.asyncio
async def test_selecting_a_field_leaf_filters_by_field_value():
    client = _FacetClient()
    async with _app(client).run_test() as pilot:
        await pilot.pause()
        tree = pilot.app.query_one("#facet-tree", Tree)
        report = tree.root.children[1].children[1]         # doc_type > report
        tree.select_node(report)
        await pilot.pause()
        assert client.last["field"] == "doc_type" and client.last["value"] == "report"


@pytest.mark.asyncio
async def test_tab_moves_focus_from_table_to_the_tree():
    async with _app(_FacetClient()).run_test() as pilot:
        await pilot.pause()
        pilot.app.query_one("#table", DataTable).focus()
        await pilot.pause()
        await pilot.press("shift+tab")                     # cycle toward the rail
        await pilot.pause()
        assert isinstance(pilot.app.focused, Tree)


@pytest.mark.asyncio
async def test_enter_on_the_tree_does_not_descend_into_a_document():
    # enter descends ONLY when the table is focused; on the tree it is the Tree's
    # own select/expand, never a document push.
    from shapes.corpus.renderer.tui.document import DocumentScreen
    async with _app(_FacetClient()).run_test() as pilot:
        await pilot.pause()
        tree = pilot.app.query_one("#facet-tree", Tree)
        tree.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, DocumentScreen)   # stayed on the catalogue


@pytest.mark.asyncio
async def test_enter_on_the_table_still_descends():
    from shapes.corpus.renderer.tui.document import DocumentScreen
    async with _app(_FacetClient()).run_test() as pilot:
        await pilot.pause()
        pilot.app.query_one("#table", DataTable).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DocumentScreen)       # descent intact from the table


@pytest.mark.asyncio
async def test_arrow_left_collapses_the_open_branch_then_steps_to_parent():
    async with _app(_FacetClient()).run_test() as pilot:
        await pilot.pause()
        tree = pilot.app.query_one("#facet-tree", Tree)
        tree.focus()
        await pilot.pause()
        status = tree.root.children[0]
        tree.move_cursor(status)
        await pilot.pause()
        assert status.is_expanded
        await pilot.press("left")                      # collapse the open branch
        await pilot.pause()
        assert not status.is_expanded
        await pilot.press("right")                     # expand again
        await pilot.pause()
        assert status.is_expanded
        tree.move_cursor(status.children[1])           # onto a leaf
        await pilot.pause()
        await pilot.press("left")                      # leaf -> step to parent
        await pilot.pause()
        assert tree.cursor_node is status
