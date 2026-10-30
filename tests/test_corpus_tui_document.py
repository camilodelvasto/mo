# tests/test_corpus_tui_document.py
import pytest
from textual.app import App as TextualApp
from textual.widgets import Markdown, OptionList, Tree

from shapes.corpus.renderer.tui import keymap
from shapes.corpus.renderer.tui.document import DocumentScreen


class _DocClient:
    def __init__(self):
        self._transcript = "# Über\n\nWohnung schön text here.\n\n## Miete\n\nBefristet.\n"
        self.path_calls = []
        self.assert_calls = []
    async def doc(self, doc_id):
        return {"doc_id": doc_id, "status": "complete",
                "flow": {"id": "corpus-prep", "version": 4},
                "fields": {
                    "tipo_documento": {"value": "interview",
                        "provenance": {"stage": "classify", "by": "model", "capability": "local.llm",
                                       "finished": "2026-06-02T09:42:55Z", "confidence": 0.93}},
                    "tema": {"value": "vivienda",
                        "provenance": {"stage": "characterize", "by": "model"}}}}
    async def fields(self):
        return {"fields": {
            "tipo_documento": {"type": "enum",
                               "values": ["interview", "report", "memo"], "by": "model"},
            "tema": {"type": "string", "by": "model"},
            "tags": {"type": "set", "of": "string", "by": "operator"},
            "visibility": {"type": "enum",
                           "values": ["general", "internal", "restricted"],
                           "by": "operator"}}}
    async def post_assert(self, body):
        self.assert_calls.append(body)
        return {"inbox": "inbox/assert-001.yaml"}
    async def chunks(self, doc_id):
        return {"chunks": [
            {"ref": "c0001aaaa", "ast_path": "Über", "span": [0, 8],
             "contiguous": True, "size": 8, "vector": False},
            {"ref": "c0002bbbb", "ast_path": "Über > Miete", "span": [33, 41],
             "contiguous": True, "size": 8, "vector": False}]}
    async def log(self, doc_id):
        return {"entries": [
            {"id": "received", "entrypoint": "private"},
            {"id": "classify", "model": {"name": "llama-3.3-70b"},
             "meters": {"duration_ms": 4100, "confidence": 0.93},
             "fields": {"tipo_documento": "interview"}}]}
    async def custody(self, doc_id):
        return {"links": [
            {"stage": "received", "artifact": "original", "input": "0", "output": "0",
             "verified": True, "artifact_present": True}]}
    async def artifact(self, doc_id, name):
        return self._transcript.encode("utf-8")
    async def doc_path(self, doc_id, name="original"):
        self.path_calls.append((doc_id, name))
        return f"/corpus/{doc_id}/original.pdf"


def _bindings():
    return keymap.load_bindings(
        keymap.Path("shapes/corpus/renderer/tui/bindings.default.yaml"),
        keymap.Path("."), keymap.READ_CAPABILITIES)


class _Host(TextualApp):
    def __init__(self, client):
        super().__init__()
        self._client = client
    async def on_mount(self):
        await self.push_screen(DocumentScreen("3f9a21abcdef", self._client, _bindings()))


@pytest.mark.asyncio
async def test_lands_on_document_in_prose_with_the_tree_rail():
    async with _Host(_DocClient()).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        tree = scr.query_one("#doc-tree", Tree)
        assert [str(n.label) for n in tree.root.children] == [
            "document", "fields", "pipeline", "custody"]
        assert scr.query_one("#prose-md", Markdown)
        assert scr._reading == "document"


@pytest.mark.asyncio
async def test_inspector_shows_fields_on_load():
    async with _Host(_DocClient()).run_test() as pilot:
        await pilot.pause()
        inspector = str(pilot.app.screen.query_one("#inspector").renderable)
        assert "INSPECTOR" in inspector
        assert "tipo_documento:" in inspector
        assert "interview" in inspector
        assert "tema:" in inspector
        assert "vivienda" in inspector


@pytest.mark.asyncio
async def test_r_toggles_prose_to_chunks_and_span_lights():
    async with _Host(_DocClient()).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        scr.query_one("#doc-tree", Tree).focus()
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert scr.query_one("#chunk-list", OptionList).option_count == 2
        assert "Wohnung" in str(scr.query_one("#transcript-view").renderable)
        await pilot.press("r")
        await pilot.pause()
        assert scr.query_one("#prose-md", Markdown)


@pytest.mark.asyncio
async def test_fields_reading_shows_table_and_provenance():
    async with _Host(_DocClient()).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        tree = scr.query_one("#doc-tree", Tree)
        tree.select_node(tree.root.children[1])
        await pilot.pause()
        opt = scr.query_one("#field-list", OptionList)
        assert opt.option_count == 2
        first = str(opt.get_option_at_index(0).prompt)
        assert "tipo_documento: interview" in first
        assert "added by local.llm on 02.06.2026 at 09:42 · 0.93" in first   # the trail
        assert "stage: classify" in str(scr.query_one("#inspector").renderable)


@pytest.mark.asyncio
async def test_pipeline_reading_shows_the_stages():
    async with _Host(_DocClient()).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        tree = scr.query_one("#doc-tree", Tree)
        tree.select_node(tree.root.children[2])
        await pilot.pause()
        view = str(scr.query_one("#pipeline-view").renderable)
        assert "received" in view and "classify" in view
        assert "tipo_documento: interview" in view


@pytest.mark.asyncio
async def test_custody_reading_shows_the_chain():
    async with _Host(_DocClient()).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        tree = scr.query_one("#doc-tree", Tree)
        tree.select_node(tree.root.children[3])
        await pilot.pause()
        assert "verified" in str(scr.query_one("#custody-view").renderable)


@pytest.mark.asyncio
async def test_selecting_a_stage_leaf_details_it_in_the_inspector():
    async with _Host(_DocClient()).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        tree = scr.query_one("#doc-tree", Tree)
        pipeline = tree.root.children[2]
        tree.select_node(pipeline.children[1])
        await pilot.pause()
        assert "STAGE · classify" in str(scr.query_one("#inspector").renderable)


@pytest.mark.asyncio
async def test_o_reveals_the_original(monkeypatch):
    import shapes.corpus.renderer.tui.document as document_mod
    revealed = []
    monkeypatch.setattr(document_mod, "reveal", lambda p: revealed.append(p))
    client = _DocClient()
    async with _Host(client).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        scr.query_one("#doc-tree", Tree).focus()
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert ("3f9a21abcdef", "original") in client.path_calls
        assert revealed == ["/corpus/3f9a21abcdef/original.pdf"]



@pytest.mark.asyncio
async def test_rail_renders_readings_at_top_no_empty_root():
    # The rail hides the empty root (show_root=False) so the readings render
    # directly — both robust against the pushed-screen collapsed-root bug and
    # consistent with the catalogue. Without it, line 0 is the empty root.
    async with _Host(_DocClient()).run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        tree = pilot.app.screen.query_one("#doc-tree", Tree)
        assert tree.show_root is False
        assert "document" in tree.render_line(0).text     # a reading, not an empty root


@pytest.mark.asyncio
async def test_prose_is_scrollable_and_focusable():
    from textual.containers import VerticalScroll
    client = _DocClient()
    client._transcript = "# Doc\n\n" + ("Una línea larga de texto. " * 8 + "\n\n") * 40
    async with _Host(client).run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()
        prose = pilot.app.screen.query_one("#prose", VerticalScroll)
        assert prose.can_focus                              # tab can reach it
        assert prose.virtual_size.height > prose.size.height  # content overflows -> scrolls


@pytest.mark.asyncio
async def test_chunk_mode_scrolls_a_far_down_span_into_view_with_wrapping():
    # WRAPPING prose: two long unbroken paragraphs render to many visual lines, so
    # a raw newline count is wrong — the span must scroll into the visible window
    # by its VISUAL position. The old line-count scroll left it off-screen.
    from textual.containers import VerticalScroll
    client = _DocClient()
    client._transcript = "# Top\n\n" + ("palabra " * 200) + "\n\n" + ("relleno " * 200) + "\n\nMARCA.\n"
    start = client._transcript.index("MARCA")
    async def _chunks(doc_id):
        return {"chunks": [
            {"ref": "c1", "ast_path": "Top", "span": [0, 4],
             "contiguous": True, "size": 4, "vector": False},
            {"ref": "c2", "ast_path": "Marca", "span": [start, start + 5],
             "contiguous": True, "size": 5, "vector": False}]}
    client.chunks = _chunks
    async with _Host(client).run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        scr.query_one("#doc-tree", Tree).focus()
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        sc = scr.query_one("#transcript-scroll", VerticalScroll)
        assert sc.scroll_offset.y == 0                      # chunk 0 at top
        scr.query_one("#chunk-list", OptionList).highlighted = 1
        for _ in range(3):
            await pilot.pause()
        # the span's visual line lands inside the scrolled viewport (not off-screen)
        vline = int(start / len(client._transcript) * sc.virtual_size.height)
        top, bottom = sc.scroll_offset.y, sc.scroll_offset.y + sc.size.height
        assert top <= vline <= bottom


@pytest.mark.asyncio
async def test_e_opens_edit_panel_with_all_fields():
    """Pressing `e` on the document screen opens the edit panel with all fields
    from /fields — not just operator-writable ones."""
    from textual.containers import VerticalScroll
    from textual.widgets import Input, Label, Select
    client = _DocClient()
    async with _Host(client).run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        scr.query_one("#doc-tree", Tree).focus()
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()  # extra pause for async mount
        panel = scr.query_one("#edit-panel", VerticalScroll)
        # All 4 fields should be present
        labels = [w for w in panel.children if isinstance(w, Label)
                  and w.has_class("edit-field-name")]
        assert len(labels) == 4
        field_names = [str(l.render()) for l in labels]
        assert "tipo_documento" in field_names
        assert "tema" in field_names
        assert "tags" in field_names
        assert "visibility" in field_names
        # enum → Select, string → Input, set → add/remove Inputs
        assert scr.query_one("#edit-tipo_documento", Select)
        assert scr.query_one("#edit-tema", Input)
        assert scr.query_one("#edit-tags-add", Input)
        assert scr.query_one("#edit-tags-rm", Input)
        assert scr.query_one("#edit-visibility", Select)


@pytest.mark.asyncio
async def test_esc_from_edit_returns_to_normal_view():
    from textual.containers import VerticalScroll
    client = _DocClient()
    async with _Host(client).run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        scr.query_one("#doc-tree", Tree).focus()
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()
        assert scr._editing is True
        await pilot.press("escape")
        await pilot.pause()
        assert scr._editing is False
        # edit panel removed, inspector visible again
        assert scr.query_one("#inspector").display is True


@pytest.mark.asyncio
async def test_save_edit_updates_panel_with_new_values():
    """After saving, the edit panel rebuilds with the asserted values
    (optimistic update) so the user sees what they wrote."""
    from textual.widgets import Input, Select
    client = _DocClient()
    async with _Host(client).run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        scr.query_one("#doc-tree", Tree).focus()
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()
        # change tema from "vivienda" to "educación"
        tema_input = scr.query_one("#edit-tema", Input)
        tema_input.value = "educación"
        # click Save
        scr.query_one("#edit-save").press()
        await pilot.pause()
        await pilot.pause()
        # assert was called with the change
        assert len(client.assert_calls) == 1
        assert client.assert_calls[0]["fields"]["tema"] == "educación"
        # the panel rebuilt with the new value
        new_input = scr.query_one("#edit-tema", Input)
        assert new_input.value == "educación"
