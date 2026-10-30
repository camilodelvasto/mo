# tests/test_corpus_tui_catalogue.py
import pytest

from shapes.corpus.renderer.tui import keymap
from shapes.corpus.renderer.tui.app import CatalogueApp


class _FakeClient:
    """Canned service responses; records what was asked."""
    def __init__(self):
        self.last_catalogue = None
        self.rows = {"3f9a21abcdef": {"doc_id": "3f9a21abcdef", "status": "complete",
                                      "cells": {"doc_type": {"value": "interview", "by": "model"}}}}
        self.engine_up = False
        self.count = 1

    async def status(self):
        return {"counts": {"all": self.count, "hard": 0, "soft": 0, "retired": 0,
                           "quarantine": 0}, "engine": self.engine_up, "service": True}

    async def counts(self):
        return {"all": self.count, "hard": 0, "soft": 0, "retired": 0, "quarantine": 0}

    async def facets(self):
        return {"facets": [
            {"key": "status", "values": [
                {"value": "all", "count": self.count},
                {"value": "pending", "count": 0}, {"value": "done", "count": 0}]},
            {"key": "doc_type", "values": [{"value": "interview", "count": self.count}]}]}

    async def catalogue(self, lens="all", where="", field=None, value=None,
                        cursor=0, limit=100):
        self.last_catalogue = {"lens": lens, "where": where,
                               "field": field, "value": value}
        rows = list(self.rows.values()) if self.count else []
        return {"rows": rows, "cursor": None, "total": len(rows)}

    async def row(self, doc_id):
        return self.rows.get(doc_id)

    async def doc(self, doc_id):
        return {"doc_id": doc_id, "status": "complete",
                "flow": {"id": "corpus-prep", "version": 4, "hash": "sha256:8c"},
                "fields": {"doc_type": {"value": "interview",
                    "provenance": {"stage": "classify", "by": "model"}}}}

    async def custody(self, doc_id):
        return {"links": []}

    async def chunks(self, doc_id):
        return {"chunks": []}

    async def log(self, doc_id):
        return {"entries": []}

    async def artifact(self, doc_id, name):
        return b""

    async def doc_path(self, doc_id, name="original"):
        return f"/corpus/{doc_id}/original"

    async def aclose(self):
        pass


def _flow_declared():
    return ["doc_type", "consent", "tags"]


def _app(client):
    bindings = keymap.load_bindings(
        keymap.Path("shapes/corpus/renderer/tui/bindings.default.yaml"),
        keymap.Path("."), keymap.READ_CAPABILITIES)
    return CatalogueApp(client=client, declared=_flow_declared(), bindings=bindings)


@pytest.mark.asyncio
async def test_initial_load_fills_the_table_and_counts():
    client = _FakeClient()
    async with _app(client).run_test() as pilot:
        from textual.widgets import DataTable
        table = pilot.app.query_one("#table", DataTable)
        assert table.row_count == 1
        assert "all" in str(pilot.app.query_one("#footer-line").renderable)


@pytest.mark.asyncio
async def test_lens_key_switches_the_lens():
    client = _FakeClient()
    async with _app(client).run_test() as pilot:
        await pilot.press("2")                      # bound to lens pending
        assert client.last_catalogue["lens"] == "pending"


@pytest.mark.asyncio
async def test_refetch_doc_id_fetches_one_row():
    client = _FakeClient()
    async with _app(client).run_test() as pilot:
        await pilot.app.refetch("3f9a21abcdef")     # granular path
        from textual.widgets import DataTable
        assert pilot.app.query_one("#table", DataTable).row_count == 1


@pytest.mark.asyncio
async def test_stopped_engine_is_visible_in_the_header():
    client = _FakeClient()
    client.engine_up = False
    async with _app(client).run_test() as pilot:
        header = str(pilot.app.query_one("#header-line").renderable)
        assert "stopped" in header.lower() or "○" in header


@pytest.mark.asyncio
async def test_empty_lens_shows_an_explicit_empty_state():
    client = _FakeClient()
    client.count = 0
    async with _app(client).run_test() as pilot:
        assert pilot.app.query_one("#table").row_count == 0
        assert "no documents" in str(pilot.app.query_one("#empty-state").renderable).lower()


@pytest.mark.asyncio
async def test_columns_are_resized_to_proportional_widths():
    from textual.widgets import DataTable
    from shapes.corpus.renderer.tui import render
    client = _FakeClient()
    async with _app(client).run_test(size=(160, 40)) as pilot:
        await pilot.pause()                       # let the deferred apply run
        table = pilot.app.query_one("#table", DataTable)
        cols = pilot.app._columns
        available = max(table.size.width, len(cols) * render.MIN_COL)
        expected = render.column_widths(cols, available)
        assert available > len(cols) * render.MIN_COL   # the table is really laid out
        for col_key, name in zip(pilot.app._col_keys, cols):
            col = table.columns[col_key]
            assert col.auto_width is False        # content auto-sizing is off
            assert col.width == expected[name]    # the proportional width took
        # the trailing free-text column is the widest
        widest = max(table.columns.values(), key=lambda c: c.width)
        assert widest.width == expected[cols[-1]]


@pytest.mark.asyncio
async def test_columns_reflow_to_the_new_width_after_a_resize():
    # After the terminal grows, re-applying the widths must fill the wider row:
    # the proportional widths track the table's current measured width, not the
    # width it had at first load.
    from textual.widgets import DataTable
    from shapes.corpus.renderer.tui import render
    client = _FakeClient()
    async with _app(client).run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        table = pilot.app.query_one("#table", DataTable)
        cols = pilot.app._columns
        narrow = table.columns[pilot.app._col_keys[-1]].width
        await pilot.resize_terminal(240, 50)
        # let the table settle to its new measured width, then re-flow
        for _ in range(6):
            await pilot.pause()
        pilot.app._applied_width = -1          # force a fresh apply at this size
        pilot.app._apply_column_widths()
        await pilot.pause()
        expected = render.column_widths(
            cols, max(table.size.width, len(cols) * render.MIN_COL))
        for col_key, name in zip(pilot.app._col_keys, cols):
            assert table.columns[col_key].width == expected[name]
        # the wider terminal gave the free-text column more room than before
        assert table.columns[pilot.app._col_keys[-1]].width > narrow


@pytest.mark.asyncio
async def test_selecting_a_row_fills_the_inspector():
    client = _FakeClient()
    client.rows["3f9a21abcdef"]["proposals"] = {
        "tags": {"add": ["berlin"], "confidence": 0.71}}
    async with _app(client).run_test() as pilot:
        await pilot.pause()                          # first row highlighted on load
        insp = str(pilot.app.query_one("#inspector").renderable)
        assert "3f9a21" in insp and "~tags" in insp and "0.71" in insp


@pytest.mark.asyncio
async def test_row_highlighted_with_no_current_row_does_not_crash():
    # Textual fires RowHighlighted(cursor_row=-1, row_key=None) when the cursor
    # clears (empty lens, mid-reconcile, esc-return). The handler must not do
    # None.value — that crashed the whole app.
    from textual.widgets import DataTable
    async with _app(_FakeClient()).run_test() as pilot:
        await pilot.pause()
        table = pilot.app.query_one("#table", DataTable)
        await pilot.app.on_data_table_row_highlighted(
            DataTable.RowHighlighted(table, -1, None))
        await pilot.pause()
        assert str(pilot.app.query_one("#inspector").renderable) == ""   # cleared, no crash


@pytest.mark.asyncio
async def test_inspector_shows_the_full_document_fields():
    # The table truncates long fields (tema); the inspector shows the highlighted
    # document's full field values — "more of the document" in the right pane.
    client = _FakeClient()
    long_tema = "Una descripción larga del tema que no cabe en la columna de la tabla"
    client.rows["3f9a21abcdef"]["cells"]["doc_type"] = {"value": long_tema, "by": "model"}
    async with _app(client).run_test() as pilot:
        await pilot.pause()
        insp = str(pilot.app.query_one("#inspector").renderable)
        assert "doc_type:" in insp
        assert long_tema in insp                       # full value, not truncated
