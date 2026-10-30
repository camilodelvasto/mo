# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The catalogue screen logic, mixed into CatalogueApp. Fills the frame from the
service, owns the refetch(target) seam, dispatches capability keys through the
keymap, and renders the stopped-engine header and the empty-lens state. Holds no
optimistic state — every change is a re-fetch."""
from pathlib import Path

from textual.widgets import DataTable, Static, Tree

from shapes.corpus.renderer.tui import facets as facetmod
from shapes.corpus.renderer.tui import labels as labelmod
from shapes.corpus.renderer.tui import render
from shapes.corpus.renderer.tui.keymap import footer_text


class CatalogueMixin:
    """Mixed into CatalogueApp (an App). Expects self.client, self.declared,
    self.bindings, self.lens, self._rows_by_id set by the App."""

    async def load_initial(self) -> None:
        self._columns = render.table_columns(self.declared)
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        # Add columns with explicit string keys so update_cell works by string.
        # Pass (label, key) tuples so column keys match column names exactly.
        self._col_keys = table.add_columns(
            *[(col, col) for col in self._columns]
        )
        # Defer the width apply until after the first layout pass — at this point
        # the table has no measured size yet (size.width == 0 before layout), so
        # reading it now would collapse every column to MIN_COL.
        self.call_after_refresh(self._apply_column_widths)
        self.query_one("#footer-line", Static).update(footer_text(self.bindings))
        await self._render_status()
        await self.refetch("all")

    def _apply_column_widths(self) -> None:
        table = self.query_one("#table", DataTable)
        available = table.size.width
        floor = len(self._columns) * render.MIN_COL
        # Apply ONLY a SETTLED width: it must be >= floor AND stable across two
        # consecutive reads. A resize/focus cascade reports transient widths (0,
        # or in-flight values) for a frame or two; applying ANY of those is the
        # visible "columns jump" (collapsed at 0, cramped at an in-flight value).
        # So we wait for the width to hold steady, keeping the last good widths,
        # and never apply a transient.
        if available < floor or available != self._last_width_seen:
            self._last_width_seen = available
            if self._width_retries < 16:
                self._width_retries += 1
                self.call_after_refresh(self._apply_column_widths)
            return
        self._width_retries = 0
        if available == self._applied_width:
            return                              # already sized for this width
        self._applied_width = available
        widths = render.column_widths(self._columns, available)
        for col_key, name in zip(self._col_keys, self._columns):
            col = table.columns[col_key]
            col.auto_width = False
            col.width = widths[name]
        # textual 8.2.5: setting col.width invalidates the layout/offset cache but
        # NOT the per-cell render cache — already-rendered rows keep their stale
        # (wider) cells until individually touched (a cursor move), so rows render
        # at INCONSISTENT widths: the visible "jump". _clear_caches() drops the
        # row/cell/line caches so every row re-renders at the new widths at once.
        # (Private; a version bump that renames it must fail loudly, not silently.)
        table._clear_caches()
        table._require_update_dimensions = True
        table.refresh(layout=True)

    async def on_resize(self, event) -> None:
        # Re-flow when the terminal changes size. The width settles a frame or two
        # after this event; reset the latch so the deferred apply waits for the new
        # width to hold steady (it never applies an in-flight value).
        if getattr(self, "_col_keys", None):
            self._applied_width = -1
            self._last_width_seen = -1
            self._width_retries = 0
            self.call_after_refresh(self._apply_column_widths)

    async def refetch(self, target) -> None:
        # In embed mode the FastAPI startup poller never fires — the cache
        # must be ticked explicitly before each read so sidecar changes land.
        svc = getattr(self, "_service_app", None)
        if svc is not None:
            svc.state.poll_once()
        if target == "all":
            self._build_tree(await self.client.facets())
            page = await self.client.catalogue(
                lens=self.lens, field=self.facet_field, value=self.facet_value)
            # Idle ticks are free: only touch the table when the data actually
            # changed. The 1.5s poll otherwise rewrote every visible cell every
            # tick, repainting (and flickering the cursor) for nothing. The first
            # load always fills (so an empty lens renders its empty-state).
            if not self._loaded or page["rows"] != self._all_rows:
                self._fill_table(page["rows"])
                self._loaded = True
        else:
            row = await self.client.row(target)
            if row is not None:
                self._upsert_row(row)

    def _fill_table(self, rows) -> None:
        self._rows_by_id = {r["doc_id"]: r for r in rows}
        self._all_rows = list(rows)               # the current view's rows
        self._sync_table()

    def _visible_rows(self) -> list:
        """The current view's rows, narrowed by the unified search: a row shows
        if its metadata substring-matches OR its content matched /search."""
        q = getattr(self, "_search", "").lower()
        hits = getattr(self, "_content_hits", set())
        if not q:
            return self._all_rows
        out = []
        for r in self._all_rows:
            hay = " ".join([r["doc_id"], r["status"], r.get("source_name", ""),
                            *[render._set_str(c["value"])
                              for c in r.get("cells", {}).values()]]).lower()
            if q in hay or r["doc_id"] in hits:
                out.append(r)
        return out

    def _sync_table(self) -> None:
        table = self.query_one("#table", DataTable)
        rows = self._visible_rows()
        desired = [r["doc_id"] for r in rows]
        current = [table.coordinate_to_cell_key((i, 0)).row_key.value
                   for i in range(table.row_count)]
        if desired == current:                    # common tick: update in place
            for r in rows:
                for col_key, value in zip(self._col_keys,
                                          render.render_row(r, self._columns)):
                    table.update_cell(r["doc_id"], col_key, value)
        else:                                     # set/order changed: rebuild + restore
            keep = (table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                    if table.row_count else None)
            table.clear()
            for r in rows:
                table.add_row(*render.render_row(r, self._columns), key=r["doc_id"])
            if keep in desired:
                table.move_cursor(row=desired.index(keep))
        self.query_one("#empty-state", Static).update(
            "" if rows else "no documents in this view")

    def _upsert_row(self, row) -> None:
        table = self.query_one("#table", DataTable)
        self._rows_by_id[row["doc_id"]] = row
        cells = render.render_row(row, self._columns)
        if row["doc_id"] in table.rows:
            # RowKey.__eq__ compares equal to a plain string
            for col_key, value in zip(self._col_keys, cells):
                table.update_cell(row["doc_id"], col_key, value)
        else:
            table.add_row(*cells, key=row["doc_id"])

    def _render_inspector(self, doc_id) -> None:
        row = self._rows_by_id.get(doc_id)
        if not row:
            self.query_one("#inspector", Static).update("")
            return
        lines = [f"INSPECTOR · {doc_id[:6]}", "", row["status"], ""]
        # the document's full field values — the table truncates them (esp. tema);
        # the inspector shows them whole, wrapped.
        for fld, cell in (row.get("cells") or {}).items():
            lines.append(f"{fld}:")
            lines.append(f"  {render._set_str(cell['value'])}")
        for fld, prop in (row.get("proposals") or {}).items():
            conf = f" ({prop['confidence']:.2f})" if "confidence" in prop else ""
            val = ", ".join(prop.get("add", [])) or str(prop.get("value", ""))
            lines.append(f"~{fld}: {val}{conf}")
        for fld in (row.get("pending") or []):
            lines.append(f"◌{fld} in-flight")
        snippet = getattr(self, "_snippets", {}).get(doc_id)
        if snippet:
            lines += ["", "match:", f"  {snippet[:200]}"]
        self.query_one("#inspector", Static).update("\n".join(lines))

    async def on_data_table_row_highlighted(self, event) -> None:
        # Textual fires this with row_key=None when the cursor clears (empty lens,
        # a mid-reconcile clear(), esc-return) — never do None.value, it crashed
        # the app. No current row → empty inspector.
        if event.row_key is None:
            self.query_one("#inspector", Static).update("")
            return
        self._render_inspector(str(event.row_key.value))

    def _build_tree(self, payload) -> None:
        # Build only when the facet data changed — rebuilding every 1.5s tick
        # would steal rail focus and collapse the tree cursor (same reconcile
        # discipline as the table).
        if payload == getattr(self, "_facets_cache", None):
            return
        self._facets_cache = payload
        tree = self.query_one("#facet-tree", Tree)
        tree.clear()
        self._labels = labelmod.load(self.corpus_dir or Path("."))
        for cat in facetmod.facet_nodes(payload, lambda k: labelmod.label(self._labels, k)):
            node = tree.root.add(cat["label"], expand=True)
            for leaf in cat["leaves"]:
                node.add_leaf(f"{leaf['label']}  {leaf['count']}", data=leaf["select"])
        tree.root.expand()

    async def on_tree_node_selected(self, event) -> None:
        sel = event.node.data
        if sel is None:                       # a category row, not a leaf
            return
        key, value = sel
        if key == "status":
            self.lens, self.facet_field, self.facet_value = value, None, None
        else:
            self.lens, self.facet_field, self.facet_value = "all", key, value
        await self.refetch("all")

    async def _render_status(self) -> None:
        s = await self.client.status()
        def dot(up):
            return "●" if up else "○"
        stopped = "" if s["engine"] else "  engine: stopped"
        self.query_one("#header-line", Static).update(
            f"moui · catalogue        engine {dot(s['engine'])}  "
            f"serve {dot(s['service'])}  index ○{stopped}")

    async def set_lens(self, lens) -> None:
        self.lens = lens
        self.facet_field = self.facet_value = None   # a status accelerator clears any field facet
        await self.refetch("all")
