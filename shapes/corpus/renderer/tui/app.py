# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""CatalogueApp — the read-only catalogue Textual app. An httpx client (embed by
default), the keymap-driven capability dispatch, the timer trigger, and the
stopped/empty states. It GETs the service and renders; it writes no sidecar."""
from pathlib import Path

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Input, Static

from shapes.corpus.renderer.tui import keymap
from shapes.corpus.renderer.tui.catalogue import CatalogueMixin
from shapes.corpus.renderer.tui.client import embed_client
from shapes.corpus.renderer.tui.reveal import reveal
from shapes.corpus.renderer.tui.ask_screen import AskScreen
from shapes.corpus.renderer.tui.document import DocumentScreen
from shapes.corpus.renderer.tui.frame import SPINE_BINDINGS, RendStatic, compose_frame
from shapes.corpus.renderer.tui.trigger import TimerTrigger

_DEFAULT_BINDINGS = Path(__file__).parent / "bindings.default.yaml"


class CatalogueApp(CatalogueMixin, App):
    CSS_PATH = "app.tcss"
    # Search toggles on "/" — shift+7 on a Spanish keyboard, the universal search
    # key (vim/less) everywhere. A priority binding so it reaches the app even
    # while the search Input has focus (the Input would otherwise swallow it);
    # priority=True preempts the focused widget. The close-on-"/" while the Input
    # is focused is owned by SearchInput (a focused Input eats the char first).
    BINDINGS = SPINE_BINDINGS + [
        Binding("slash", "toggle_search", "search", show=False, priority=True),
    ]

    def __init__(self, corpus_dir: Path | None = None, machine_root: Path | None = None,
                 *, client=None, declared=None, bindings=None, trigger=None, asks=None,
                 ask_defaults=None):
        super().__init__()
        self._service_app = None
        if client is None:
            client, self._service_app = embed_client(corpus_dir, machine_root)
        self.client = client
        self.corpus_dir = corpus_dir
        self.declared = declared if declared is not None else []
        self.asks = asks if asks is not None else []
        self.ask_defaults = ask_defaults if ask_defaults is not None else {}
        self.bindings = bindings if bindings is not None else keymap.load_bindings(
            _DEFAULT_BINDINGS, corpus_dir or Path("."), keymap.READ_CAPABILITIES)
        self._trigger = trigger or TimerTrigger()
        self.lens = "all"
        self.facet_field = None
        self.facet_value = None
        self._rows_by_id = {}
        self._all_rows = []
        self._loaded = False       # the first refetch always fills (even an empty lens)
        self._search = ""
        self._content_hits = set()     # doc_ids matched by the /search content query
        self._snippets = {}            # doc_id -> best matching passage
        self._search_timer = None      # debounce handle for the content query
        self._search_gen = 0           # supersede stale in-flight content queries
        self._col_keys = []
        self._applied_width = -1   # last table width the columns were sized for
        self._last_width_seen = -1  # previous read, to apply only a settled width
        self._width_retries = 0    # bounded re-arm while the table width settles
        self._by_key = {b.key: b for b in self.bindings}

    def compose(self) -> ComposeResult:
        yield from compose_frame()
        yield RendStatic(id="empty-state")

    async def on_mount(self) -> None:
        await self.load_initial()
        self.query_one("#table").focus()
        self._trigger.start(self)

    async def on_key(self, event) -> None:
        if event.key == "enter" and isinstance(self.focused, DataTable):
            event.stop()                       # enter descends ONLY from the table;
            await self._descend()              # on the tree it selects/expands the node
            return
        binding = self._by_key.get(event.key)
        if binding is None or binding.capability == "filter":
            return                            # filter is the document screen's
        event.stop()
        if binding.capability == "lens":
            await self.set_lens(binding.args["lens"])
        elif binding.capability == "open-artifact":
            await self._open_selected_original()
        elif binding.capability == "ask":
            await self.push_screen(AskScreen(self.corpus_dir, self.asks, self.ask_defaults))

    async def _descend(self) -> None:
        table = self.query_one("#table", DataTable)
        if table.row_count == 0:
            return
        doc_id = str(table.coordinate_to_cell_key(
            table.cursor_coordinate).row_key.value)
        await self.push_screen(DocumentScreen(doc_id, self.client, self.bindings))

    async def action_toggle_search(self) -> None:
        bar = self.query_one("#search-bar", Input)
        if bar.has_class("open"):
            bar.remove_class("open")
            bar.value = ""
            self._search = ""
            self._content_hits, self._snippets = set(), {}
            self._sync_table()
            self.query_one("#table").focus()
        else:
            bar.add_class("open")
            bar.focus()

    async def on_input_changed(self, event) -> None:
        if event.input.id == "search-bar":
            self._search = event.value.strip()
            self._sync_table()                       # instant metadata narrow
            if self._search_timer is not None:
                self._search_timer.stop()
            self._search_timer = self.set_timer(0.25, self._content_search)

    async def _content_search(self) -> None:
        """The content half of the unified /: query the index, merge doc_ids.
        Debounced by on_input_changed; guarded so a stale reply never wins."""
        q = self._search
        if not q:
            self._content_hits, self._snippets = set(), {}
            self._sync_table()
            return
        self._search_gen += 1
        gen = self._search_gen
        try:
            hits = await self.client.search(q)
        except httpx.HTTPStatusError as exc:
            if gen == self._search_gen and q == self._search:
                self.query_one("#inspector", Static).update(
                    f"content search unavailable ({exc.response.status_code})")
            return
        if gen != self._search_gen or q != self._search:
            return                                   # a newer query superseded this one
        self._content_hits = {h["doc_id"] for h in hits}
        self._snippets = {h["doc_id"]: h["snippet"] for h in hits}
        self._sync_table()

    async def on_input_submitted(self, event) -> None:
        if event.input.id == "search-bar":
            self.query_one("#table").focus()

    async def _open_selected_original(self) -> None:
        table = self.query_one("#table", DataTable)
        if table.row_count == 0:
            return
        doc_id = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        try:
            path = await self.client.doc_path(doc_id, "original")
        except httpx.HTTPStatusError as exc:
            self.query_one("#inspector", Static).update(
                f"original unavailable ({exc.response.status_code})")
            return
        if path is None:
            self.query_one("#inspector", Static).update("original unavailable (bytes gone)")
            return
        reveal(path)                       # reveal the file in the OS file manager
