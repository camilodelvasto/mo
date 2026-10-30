# tests/test_corpus_tui_search.py
import httpx
import pytest
from textual.widgets import DataTable, Input
from shapes.corpus.renderer.tui.app import CatalogueApp
from tests.test_corpus_tui_tree import _FacetClient


class _TwoRowClient(_FacetClient):
    """The shared fake returns a single row; the search test needs ≥2 rows so a
    substring narrows the table from full to one. Same shape, two distinct ids."""
    def __init__(self):
        super().__init__()
        self.rows = {
            "3f9a21abcdef": {"doc_id": "3f9a21abcdef", "status": "complete",
                             "cells": {"doc_type": {"value": "interview", "by": "model"}}},
            "7c4d88fedcba": {"doc_id": "7c4d88fedcba", "status": "complete",
                             "cells": {"doc_type": {"value": "report", "by": "model"}}},
        }
        self.count = 2


def _app():
    return CatalogueApp(client=_TwoRowClient(), declared=["doc_type", "consent", "tags"])


@pytest.mark.asyncio
async def test_shift7_opens_search_and_narrows_then_clears():
    async with _app().run_test() as pilot:
        await pilot.pause()
        table = pilot.app.query_one("#table", DataTable)
        full = table.row_count
        assert full >= 2
        await pilot.press("/")                       # shift+7 on ES → /
        await pilot.pause()
        assert isinstance(pilot.app.focused, Input) and pilot.app.focused.id == "search-bar"
        bar = pilot.app.query_one("#search-bar", Input)
        first_id = table.coordinate_to_cell_key((0, 0)).row_key.value
        bar.value = first_id
        await pilot.pause()
        assert pilot.app.query_one("#table", DataTable).row_count == 1
        await pilot.press("/")                       # toggle clears
        await pilot.pause()
        assert pilot.app.query_one("#table", DataTable).row_count == full


@pytest.mark.asyncio
async def test_search_survives_a_refetch_tick():
    async with _app().run_test() as pilot:
        await pilot.pause()
        table = pilot.app.query_one("#table", DataTable)
        first_id = table.coordinate_to_cell_key((0, 0)).row_key.value
        await pilot.press("/"); await pilot.pause()
        pilot.app.query_one("#search-bar", Input).value = first_id
        await pilot.pause()
        await pilot.app.refetch("all")               # the 1.5s tick
        await pilot.pause()
        assert pilot.app.query_one("#table", DataTable).row_count == 1   # still narrowed


class _SourceNameClient(_FacetClient):
    """One row whose declared cells do NOT contain 'petro', but whose
    source_name does — proves the filter reaches source_name."""
    def __init__(self):
        super().__init__()
        self.rows = {
            "aa11bb22cc33": {"doc_id": "aa11bb22cc33", "status": "complete",
                             "source_name": "Voté_por_Petro.txt",
                             "cells": {"doc_type": {"value": "interview", "by": "model"}}},
            "dd44ee55ff66": {"doc_id": "dd44ee55ff66", "status": "complete",
                             "source_name": "otra_cosa.txt",
                             "cells": {"doc_type": {"value": "report", "by": "model"}}},
        }
        self.count = 2


@pytest.mark.asyncio
async def test_search_matches_source_name():
    app = CatalogueApp(client=_SourceNameClient(),
                       declared=["doc_type", "consent", "tags"])
    async with app.run_test() as pilot:
        await pilot.pause()
        table = pilot.app.query_one("#table", DataTable)
        assert table.row_count == 2
        await pilot.press("/"); await pilot.pause()
        pilot.app.query_one("#search-bar", Input).value = "petro"
        await pilot.pause()
        assert pilot.app.query_one("#table", DataTable).row_count == 1


class _ContentClient(_FacetClient):
    """Two rows; neither's cells contain 'petro'. search() reports that the
    SECOND doc matches on content — the merge must surface it."""
    def __init__(self):
        super().__init__()
        self.rows = {
            "1111aaaa1111": {"doc_id": "1111aaaa1111", "status": "complete",
                             "cells": {"doc_type": {"value": "interview", "by": "model"}}},
            "2222bbbb2222": {"doc_id": "2222bbbb2222", "status": "complete",
                             "cells": {"doc_type": {"value": "report", "by": "model"}}},
        }
        self.count = 2

    async def search(self, q):
        if "petro" in q.lower():
            return [{"doc_id": "2222bbbb2222", "score": 1.0,
                     "snippet": "…voté por Petro…"}]
        return []


@pytest.mark.asyncio
async def test_content_hit_surfaces_though_metadata_does_not_match():
    app = CatalogueApp(client=_ContentClient(), declared=["doc_type", "consent", "tags"])
    async with app.run_test() as pilot:
        await pilot.pause()
        table = pilot.app.query_one("#table", DataTable)
        await pilot.press("/"); await pilot.pause()
        pilot.app.query_one("#search-bar", Input).value = "petro"
        await pilot.pause()
        await pilot.app._content_search()          # run the debounced search deterministically
        await pilot.pause()
        rows = pilot.app.query_one("#table", DataTable)
        ids = [rows.coordinate_to_cell_key((i, 0)).row_key.value
               for i in range(rows.row_count)]
        assert ids == ["2222bbbb2222"]             # metadata missed it; content found it
        # clearing search restores the full view and drops content hits
        await pilot.press("/"); await pilot.pause()
        assert pilot.app.query_one("#table", DataTable).row_count == 2
        assert pilot.app._content_hits == set()


class _FailingSearchClient(_FacetClient):
    """search() fails at the HTTP layer — _content_search must not crash the app."""
    def __init__(self):
        super().__init__()
        self.rows = {
            "1111aaaa1111": {"doc_id": "1111aaaa1111", "status": "complete",
                             "cells": {"doc_type": {"value": "interview", "by": "model"}}},
        }
        self.count = 1

    async def search(self, q):
        req = httpx.Request("GET", "http://embed/search")
        resp = httpx.Response(500, request=req)
        raise httpx.HTTPStatusError("boom", request=req, response=resp)


@pytest.mark.asyncio
async def test_content_search_survives_a_failing_search_endpoint():
    app = CatalogueApp(client=_FailingSearchClient(), declared=["doc_type", "consent", "tags"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/"); await pilot.pause()
        pilot.app.query_one("#search-bar", Input).value = "petro"
        await pilot.pause()
        await pilot.app._content_search()          # must not raise
        await pilot.pause()
        # app still alive, no content hits recorded, metadata filter still governs
        assert pilot.app._content_hits == set()
        assert pilot.app.query_one("#table", DataTable).row_count in (0, 1)
