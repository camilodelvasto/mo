# tests/test_corpus_tui_cursor.py
import pytest
from textual.widgets import DataTable
from shapes.corpus.renderer.tui.app import CatalogueApp
from tests.test_corpus_tui_catalogue import _FakeClient


def _two_row_client():
    # The shared _FakeClient returns one row; the cursor test must move down to
    # row 1, so add a second catalogue row. Assertions are unchanged: the cursor
    # must land on row 1 and stay on that same doc_id across the refetch tick.
    client = _FakeClient()
    client.rows["a1b2c3d4e5f6"] = {
        "doc_id": "a1b2c3d4e5f6", "status": "complete",
        "cells": {"doc_type": {"value": "letter", "by": "model"}}}
    client.count = 2
    return client


def _app(client):
    return CatalogueApp(client=client, declared=["doc_type", "consent", "tags"])


@pytest.mark.asyncio
async def test_cursor_stays_on_the_same_doc_across_refetch():
    async with _app(_two_row_client()).run_test() as pilot:
        await pilot.pause()
        table = pilot.app.query_one("#table", DataTable)
        await pilot.press("down")
        await pilot.pause()
        here = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        assert table.cursor_row == 1
        await pilot.app.refetch("all")            # the 1.5s tick
        await pilot.pause()
        now = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        assert now == here                        # same doc, not snapped to row 0


def _three_row_client():
    client = _FakeClient()
    client.rows["b22222222222"] = {"doc_id": "b22222222222", "status": "complete",
                                   "cells": {"doc_type": {"value": "letter", "by": "model"}}}
    client.rows["c33333333333"] = {"doc_id": "c33333333333", "status": "complete",
                                   "cells": {"doc_type": {"value": "report", "by": "model"}}}
    client.count = 3
    return client


@pytest.mark.asyncio
async def test_cursor_follows_its_doc_when_rows_change_between_fetches():
    # The rebuild branch: a row removed between fetches changes the set, so
    # _sync_table rebuilds rather than updating in place. With ≥2 rows left and
    # the cursor's doc NOT at row 0, a naive rebuild would snap the cursor to
    # row 0 — this proves it follows its doc_id to the new index instead.
    client = _three_row_client()
    async with _app(client).run_test() as pilot:
        await pilot.pause()
        table = pilot.app.query_one("#table", DataTable)
        await pilot.press("down")
        await pilot.press("down")                 # cursor to row 2 (the last doc)
        await pilot.pause()
        here = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        assert table.cursor_row == 2
        first = table.coordinate_to_cell_key((0, 0)).row_key.value   # remove row 0
        del client.rows[first]
        client.count = 2
        await pilot.app.refetch("all")            # set changed -> rebuild branch
        await pilot.pause()
        assert table.row_count == 2
        now = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        assert now == here                        # cursor followed its doc to row 1, not row 0


@pytest.mark.asyncio
async def test_idle_refetch_does_not_rewrite_the_table():
    # The 1.5s poll must be free when nothing changed: an unchanged refetch skips
    # _fill_table entirely (no cell rewrites, no repaint). _fill_table rebinds
    # self._all_rows to a fresh list, so identity-unchanged proves it was skipped.
    async with _app(_two_row_client()).run_test() as pilot:
        await pilot.pause()
        before = pilot.app._all_rows
        await pilot.app.refetch("all")            # same data -> idle tick
        await pilot.pause()
        assert pilot.app._all_rows is before      # table untouched


@pytest.mark.asyncio
async def test_columns_do_not_collapse_on_a_zero_width_settling_frame():
    # A resize/focus event makes the table briefly report width 0 mid-settle.
    # _apply_column_widths must NOT proportion against that (it would collapse
    # every column to MIN_COL — "the columns jump narrow and the data vanishes").
    import unittest.mock as mock
    from textual.geometry import Size
    from textual.widgets import DataTable
    async with _app(_two_row_client()).run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app = pilot.app
        t = app.query_one("#table", DataTable)
        wide = {n: t.columns[k].width for k, n in zip(app._col_keys, app._columns)}
        assert max(wide.values()) > 6                 # proportioned, not all at MIN_COL
        app._applied_width = -1
        with mock.patch.object(type(t), "size",
                               new_callable=mock.PropertyMock, return_value=Size(0, 40)):
            app._apply_column_widths()                # the settling 0-width frame
        after = {n: t.columns[k].width for k, n in zip(app._col_keys, app._columns)}
        assert after == wide                          # last good widths kept, no collapse


@pytest.mark.asyncio
async def test_cursor_row_and_other_rows_render_at_the_same_widths():
    # Setting col.width invalidates the layout cache but NOT the cell-render cache,
    # so a row already rendered keeps its stale (wide) render until individually
    # touched (cursor move). The visible "jump": the touched (cursor) row lays its
    # columns out differently from the untouched rows. The apply must clear the
    # render caches so every row uses the fixed widths — all rows align.
    from textual.widgets import DataTable
    client = _FakeClient()
    long_cell = {"value": "tipo-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "by": "model"}
    client.rows = {f"doc{i:09d}": {"doc_id": f"doc{i:09d}", "status": "complete",
                                   "cells": {"doc_type": dict(long_cell)}}
                   for i in range(3)}
    client.count = 3
    async with _app(client).run_test(size=(160, 30)) as pilot:
        await pilot.pause()
        await pilot.pause()
        t = pilot.app.query_one("#table", DataTable)
        t.focus()
        await pilot.pause()
        await pilot.press("down")                 # cursor to row 1 (rendered at y=2)
        await pilot.pause()
        cursor_line = t.render_line(2).text       # the cursor row
        other_line = t.render_line(3).text        # an untouched row (same data)
        # identical data past the doc_id column -> identical layout iff widths match
        assert cursor_line[14:] == other_line[14:], (
            f"cursor row laid out at different widths than its neighbour:\n"
            f"  cursor: {cursor_line!r}\n  other : {other_line!r}")
