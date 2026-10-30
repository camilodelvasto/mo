# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The three-plane frame (nav rail · main · inspector) plus header and footer
lines, and the navigation-spine bindings. Pure layout — the screen fills it with
data. Every screen mounts into this same frame, which is what lets the surface
grow (document, search) without new frames."""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Static, Tree

# The frame owns the navigation spine. arrows are the DataTable's own; enter/esc
# are Textual defaults (enter-descend wires up with the document screen, step 13).
SPINE_BINDINGS = [
    Binding("tab", "focus_next", "plane", show=False),
    Binding("q", "quit", "quit"),
    Binding("question_mark", "help", "help", show=False),
]


class RendStatic(Static):
    """Static with a .renderable property that exposes the current content.
    Textual 8.x dropped the .renderable attribute; this shim restores it so
    that test assertions like `str(widget.renderable)` work unchanged."""

    @property
    def renderable(self):
        return self.content


class SearchInput(Input):
    """The scoped-search field. "/" (shift+7 on a Spanish keyboard) toggles it;
    while it holds focus the Input's _on_key inserts "/" as a printable char
    before any binding runs, so the close-on-"/" is owned here: intercept it ahead
    of insertion and hand the toggle back to the app. The contract is unchanged —
    still an Input with id=search-bar. The app's priority binding handles the
    open-on-"/" when the table holds focus."""

    async def _on_key(self, event) -> None:
        if event.character == "/":
            event.stop()
            event.prevent_default()
            await self.app.action_toggle_search()
            return
        await super()._on_key(event)


class FacetTree(Tree):
    """The facet rail. Hides the empty root so the categories render at the top
    directly (no wasted ▼ line, and no collapsed-root failure mode — a pushed
    screen could not expand the root in time, hiding everything). Adds the
    standard tree rotation Textual's Tree omits: the left arrow collapses the
    open branch (or steps to the parent when the cursor is on a collapsed node or
    a leaf); the right arrow expands."""

    BINDINGS = [
        Binding("left", "collapse_or_parent", "collapse", show=False),
        Binding("right", "expand_node", "expand", show=False),
    ]

    def on_mount(self) -> None:
        self.show_root = False

    def action_collapse_or_parent(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and node.is_expanded:
            node.collapse()
        elif node.parent is not None and node.parent is not self.root:
            self.move_cursor(node.parent)

    def action_expand_node(self) -> None:
        node = self.cursor_node
        if node is not None and node.allow_expand and not node.is_expanded:
            node.expand()


def compose_frame() -> ComposeResult:
    yield RendStatic(id="header-line")
    with Horizontal(id="body"):
        with Static(id="nav-rail"):
            yield FacetTree("", id="facet-tree")
            yield Static("chat · 021\nreserved", id="chat-slot")
        with Vertical(id="main"):
            yield SearchInput(placeholder="search…", id="search-bar")
            yield DataTable(id="table", zebra_stripes=False, cursor_type="row")
        yield RendStatic(id="inspector")
    yield RendStatic(id="footer-line")
