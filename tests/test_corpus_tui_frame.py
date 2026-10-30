# tests/test_corpus_tui_frame.py
import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static

from shapes.corpus.renderer.tui.frame import compose_frame


class _Host(App):
    def compose(self) -> ComposeResult:
        yield from compose_frame()


@pytest.mark.asyncio
async def test_frame_mounts_the_three_planes_and_lines():
    async with _Host().run_test() as pilot:
        app = pilot.app
        assert app.query_one("#nav-rail", Static)
        assert app.query_one("#table", DataTable)
        assert app.query_one("#inspector", Static)
        assert app.query_one("#header-line", Static)
        assert app.query_one("#footer-line", Static)
