# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""DocumentScreen — the document detail, content-first. A FacetTree rail (the same
widget as the catalogue) over four readings of one sidecar: document (prose +
chunk toggle), fields (table + provenance), pipeline (the rich stages), custody.
Pushed over the catalogue on `enter`, popped on `esc`. Holds no domain logic — the
service shapes every payload; this reorganizes and formats via docrender.

Edit mode (`e`): the inspector swaps to a field-edit form. All fields shown;
operator-writable ones get edit widgets (Select for enum, Input for string/number,
add/remove for set). Model-only fields are read-only. Save asserts the changed
fields via POST /assert."""
import re

import httpx
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Markdown, OptionList, Select, Static

from shapes.corpus.renderer.tui import docrender
from shapes.corpus.renderer.tui.frame import FacetTree, RendStatic
from shapes.corpus.renderer.tui.reveal import reveal


def _slug(section: str) -> str:
    """A markdown heading anchor for a section's last path component (best-effort
    scroll target — prose reads, chunk mode does the exact span)."""
    last = section.split(">")[-1].strip()
    return re.sub(r"[^a-z0-9]+", "-", last.lower()).strip("-")


def _is_operator(spec: dict) -> bool:
    by = spec.get("by", "model")
    return by == "operator" if isinstance(by, str) else "operator" in by


class DocumentScreen(Screen):
    CSS = """
    DocumentScreen { background: #16171a; color: #c8c9cc; }
    DocumentScreen #header-line { height: 1; color: #76777b; padding: 0 1; }
    DocumentScreen #footer-line { height: 1; color: #76777b; padding: 0 1; dock: bottom; }
    DocumentScreen #body { height: 1fr; }
    DocumentScreen #nav-rail { width: 24; border-right: tall #2a2b2f; padding: 1; }
    DocumentScreen #doc-tree { height: 1fr; }
    DocumentScreen #flow-label { color: #76777b; margin-top: 1; }
    DocumentScreen #flow-pin { color: #c8c9cc; height: auto; }
    DocumentScreen #chat-slot { color: #4a4b4f; border: round #2a2b2f; margin-top: 2; }
    DocumentScreen #main { width: 1fr; padding: 0 1; }
    DocumentScreen #inspector { width: 40; border-left: tall #2a2b2f; padding: 1; color: #76777b; }
    DocumentScreen #edit-panel { width: 40; border-left: tall #2a2b2f; padding: 1; }
    DocumentScreen .edit-field-name { color: #c8c9cc; height: 1; margin-top: 1; }
    DocumentScreen .edit-readonly { color: #76777b; height: 1; }
    DocumentScreen .edit-current { color: #4a4b4f; height: 1; }
    DocumentScreen #edit-panel Input { margin-bottom: 0; }
    DocumentScreen #edit-panel Select { margin-bottom: 0; }
    DocumentScreen #edit-status { height: auto; margin-top: 1; color: #76777b; }
    DocumentScreen #prose { height: 1fr; }
    DocumentScreen #pipeline-view, DocumentScreen #custody-view { height: 1fr; }
    DocumentScreen #field-list { height: 1fr; border: none; }
    DocumentScreen #chunk-panes { height: 1fr; }
    DocumentScreen #chunk-list { width: 40%; border-right: tall #2a2b2f; }
    DocumentScreen #transcript-scroll { width: 1fr; padding: 0 1; }
    DocumentScreen #transcript-view { height: auto; }
    DocumentScreen #chunk-filter { height: 1; }
    """

    BINDINGS = [("escape", "dismiss_or_back", "back")]

    def __init__(self, doc_id: str, client, bindings=None):
        super().__init__()
        self.doc_id = doc_id
        self.client = client
        self._keymap_bindings = bindings or []
        self._by_key = {b.key: b for b in self._keymap_bindings}
        self._ready = False
        self._reading = None
        self._doc = None
        self._log = None
        self._all_chunks: list = []
        self._chunks: list = []
        self._transcript: str = ""
        self._fields_order: list = []
        self._stage_by_id: dict = {}
        self._doc_mode = "prose"          # "prose" | "chunks"
        self._editing = False
        self._field_specs: dict = {}      # name -> spec from /fields

    def compose(self):
        yield RendStatic(id="header-line")
        with Horizontal(id="body"):
            with Static(id="nav-rail"):
                yield FacetTree("", id="doc-tree")
                yield Static("flow", id="flow-label")
                yield RendStatic(id="flow-pin")
                yield Static("chat · 021\nreserved", id="chat-slot")
            yield Vertical(id="main")
            yield RendStatic(id="inspector")
        yield RendStatic(id="footer-line")

    def on_mount(self) -> None:
        self.run_worker(self._load())

    async def _load(self) -> None:
        self._doc = await self.client.doc(self.doc_id)
        chunks_payload = await self.client.chunks(self.doc_id)
        self._log = await self.client.log(self.doc_id)
        self._all_chunks = chunks_payload["chunks"]
        self._chunks = self._all_chunks
        self._stage_by_id = {s["id"]: s for s in self._log["entries"]}
        self.query_one("#header-line", RendStatic).update(
            f"moui · {self.doc_id[:6]} · {self._doc['status']}")
        self.query_one("#flow-pin", RendStatic).update(
            f"{self._doc['flow']['id']} v{self._doc['flow']['version']}")
        self.query_one("#footer-line", RendStatic).update(self._footer())
        self._build_tree()
        self.query_one("#inspector", RendStatic).update(
            "\n".join(docrender.doc_inspector(self._doc)))
        await self.show_reading("document")
        self._ready = True

    def _footer(self) -> str:
        parts = ["tab plane", "↑/↓ nav", "r raw", "j/k chunk"]
        for cap in ("filter", "open-artifact", "assert"):
            b = next((b for b in self._keymap_bindings if b.capability == cap), None)
            if b is not None:
                parts.append(f"{b.key} {b.label}")
        parts.append("esc back")
        return "   ".join(parts)

    def _build_tree(self) -> None:
        tree = self.query_one("#doc-tree", FacetTree)
        tree.clear()
        nodes = docrender.doc_nav_nodes(
            field_names=list(self._doc["fields"].keys()),
            sections=docrender.distinct_sections(self._all_chunks),
            stage_ids=[s["id"] for s in self._log["entries"]])
        for cat in nodes:
            node = tree.root.add(cat["label"], data=cat["select"], expand=True)
            for leaf in cat["leaves"]:
                node.add_leaf(leaf["label"], data=leaf["select"])
        tree.root.expand()

    async def on_tree_node_selected(self, event) -> None:
        if not self._ready:
            return
        sel = event.node.data
        if sel is None:
            return
        kind, key = sel
        if kind == "reading":
            await self.show_reading(key)
        elif kind == "section":
            await self._goto_section(key)
        elif kind == "field":
            self._show_field(key)
        elif kind == "stage":
            self._show_stage(key)

    async def show_reading(self, reading: str) -> None:
        self._reading = reading
        main = self.query_one("#main", Vertical)
        await main.remove_children()
        if reading == "document":
            await self._mount_document()
        elif reading == "fields":
            await self._mount_fields()
        elif reading == "pipeline":
            w = RendStatic(id="pipeline-view")
            await main.mount(w)
            w.update("\n".join(docrender.pipeline_rows(self._log)))
        elif reading == "custody":
            w = RendStatic(id="custody-view")
            await main.mount(w)
            payload = await self.client.custody(self.doc_id)
            w.update("\n".join(docrender.custody_links(payload)))

    async def _mount_document(self) -> None:
        main = self.query_one("#main", Vertical)
        if not self._transcript:
            raw = await self.client.artifact(self.doc_id, "transcript")
            self._transcript = raw.decode("utf-8")
        if self._doc_mode == "prose":
            await main.mount(
                VerticalScroll(Markdown(self._transcript, id="prose-md"), id="prose"))
        else:
            await main.mount(
                Horizontal(
                    OptionList(id="chunk-list"),
                    VerticalScroll(RendStatic(id="transcript-view"),
                                   id="transcript-scroll"),
                    id="chunk-panes"),
                Input(placeholder="ast_path filter…", id="chunk-filter"))
            self._fill_chunk_list()
            if self._chunks:
                self.select_chunk(0)

    async def _toggle_doc_mode(self) -> None:
        self._doc_mode = "chunks" if self._doc_mode == "prose" else "prose"
        if self._reading == "document":
            await self.show_reading("document")

    async def _goto_section(self, section: str) -> None:
        if self._reading != "document":
            await self.show_reading("document")
        if self._doc_mode == "prose":
            try:
                self.query_one("#prose-md", Markdown).goto_anchor(_slug(section))
            except Exception:
                pass
        else:
            for i, c in enumerate(self._chunks):
                if c["ast_path"] == section:
                    self.query_one("#chunk-list", OptionList).highlighted = i
                    break

    def _fill_chunk_list(self) -> None:
        opt = self.query_one("#chunk-list", OptionList)
        opt.clear_options()
        for ref, path, size in docrender.chunk_rows(self._chunks):
            opt.add_option(f"{ref}  {path}  {size}")

    def select_chunk(self, index: int) -> None:
        if not self._chunks:
            return
        index = max(0, min(index, len(self._chunks) - 1))
        chunk = self._chunks[index]
        self.query_one("#transcript-view", RendStatic).update(
            docrender.highlight(self._transcript, chunk["span"]))
        self.query_one("#inspector", RendStatic).update(
            "\n".join(docrender.chunk_inspector(chunk)))
        self.call_after_refresh(self._scroll_to_offset, chunk["span"][0])

    def _scroll_to_offset(self, offset: int) -> None:
        scroll = self.query_one("#transcript-scroll", VerticalScroll)
        height = scroll.virtual_size.height
        total = len(self._transcript) or 1
        vline = int(offset / total * height)
        scroll.scroll_to(y=max(0, vline - scroll.size.height // 3), animate=False)

    def apply_chunk_filter(self, query: str) -> None:
        self._chunks = docrender.ast_path_filter(self._all_chunks, query)
        self._fill_chunk_list()
        if self._chunks:
            self.select_chunk(0)
        else:
            self.query_one("#transcript-view", RendStatic).update("")
            self.query_one("#inspector", RendStatic).update("no chunks match")

    async def _mount_fields(self) -> None:
        opt = OptionList(id="field-list")
        self._fields_order = []
        for name, value, acquired in docrender.field_trail(self._doc):
            opt.add_option(f"{name}: {value}\n    {acquired}")
            self._fields_order.append(name)
        await self.query_one("#main", Vertical).mount(opt)
        if self._fields_order:
            self._show_field(self._fields_order[0])

    def _show_field(self, name: str) -> None:
        self.query_one("#inspector", RendStatic).update(
            "\n".join(docrender.field_provenance(self._doc, name)))

    def _show_stage(self, stage_id: str) -> None:
        s = self._stage_by_id.get(stage_id)
        if s is None:
            return
        lines = [f"STAGE · {stage_id}", ""]
        for k, v in s.items():
            if k == "id":
                continue
            lines.append(f"{k}: {v}")
        self.query_one("#inspector", RendStatic).update("\n".join(lines))

    # --- edit mode -------------------------------------------------------------

    async def _enter_edit(self) -> None:
        try:
            if not self._field_specs:
                resp = await self.client.fields()
                self._field_specs = resp["fields"]
            self._doc = await self.client.doc(self.doc_id)
        except Exception as exc:
            self.query_one("#inspector", RendStatic).update(f"fields unavailable: {exc}")
            return
        if not self._field_specs:
            self.query_one("#inspector", RendStatic).update("no fields declared")
            return
        self._editing = True
        self.query_one("#inspector", RendStatic).display = False
        body = self.query_one("#body", Horizontal)
        panel = VerticalScroll(id="edit-panel")
        await body.mount(panel)
        await self._populate_edit_panel()
        self.query_one("#footer-line", RendStatic).update(
            "tab next   enter save   esc cancel")

    async def _populate_edit_panel(self) -> None:
        panel = self.query_one("#edit-panel", VerticalScroll)
        widgets = []
        doc_fields = self._doc.get("fields", {})
        for name, spec in self._field_specs.items():
            current = doc_fields.get(name, {}).get("value")
            widgets.append(Label(name, classes="edit-field-name"))
            if spec["type"] == "enum":
                options = [(v, v) for v in spec["values"]]
                kw = {"id": f"edit-{name}", "allow_blank": True}
                if current is not None and current in spec["values"]:
                    kw["value"] = current
                widgets.append(Select(options, **kw))
            elif spec["type"] == "set":
                display = self._format_value(current)
                widgets.append(Label(f"  current: {display}", classes="edit-current"))
                widgets.append(Input(placeholder="add (comma-separated)",
                                     id=f"edit-{name}-add"))
                widgets.append(Input(placeholder="remove (comma-separated)",
                                     id=f"edit-{name}-rm"))
            else:
                widgets.append(Input(
                    value=str(current) if current is not None else "",
                    placeholder=spec["type"],
                    id=f"edit-{name}"))
        widgets.append(Button("Save", id="edit-save", variant="primary"))
        widgets.append(Static("", id="edit-status"))
        await panel.mount(*widgets)

    def _format_value(self, value) -> str:
        if value is None:
            return "—"
        if isinstance(value, list):
            return ", ".join(str(v) for v in value) if value else "—"
        return str(value)

    async def _exit_edit(self) -> None:
        self._editing = False
        try:
            panel = self.query_one("#edit-panel", VerticalScroll)
            await panel.remove()
        except Exception:
            pass
        inspector = self.query_one("#inspector", RendStatic)
        inspector.update("\n".join(docrender.doc_inspector(self._doc)))
        inspector.display = True
        self.query_one("#footer-line", RendStatic).update(self._footer())

    async def _save_edit(self) -> None:
        changed = {}
        doc_fields = self._doc.get("fields", {})
        for name, spec in self._field_specs.items():
            current = doc_fields.get(name, {}).get("value")
            try:
                new_value = self._collect_field(name, spec)
            except _Skip:
                continue
            if spec["type"] == "set":
                # set ops are always meaningful if non-empty
                if new_value:
                    changed[name] = new_value
            elif new_value != current:
                changed[name] = new_value
        if not changed:
            self.query_one("#edit-status", Static).update("no changes")
            return
        try:
            result = await self.client.post_assert(
                {"doc_id": self.doc_id, "fields": changed})
            self.query_one("#edit-status", Static).update(
                f"wrote {result['inbox']}")
            # optimistic update: patch _doc with the asserted values so the
            # edit panel reflects what the user wrote, without waiting for the
            # engine to process the inbox file
            for name, val in changed.items():
                if name not in self._doc.setdefault("fields", {}):
                    self._doc["fields"][name] = {"value": None, "provenance": {}}
                if isinstance(val, dict) and ("add" in val or "remove" in val):
                    # set ops: merge into current list
                    cur = self._doc["fields"][name].get("value") or []
                    cur = list(cur)
                    for item in val.get("add", []):
                        if item not in cur:
                            cur.append(item)
                    for item in val.get("remove", []):
                        if item in cur:
                            cur.remove(item)
                    self._doc["fields"][name]["value"] = cur
                else:
                    self._doc["fields"][name]["value"] = val
            # rebuild the edit panel with updated values
            panel = self.query_one("#edit-panel", VerticalScroll)
            await panel.remove_children()
            await self._populate_edit_panel()
            self.query_one("#edit-status", Static).update(
                f"wrote {result['inbox']}")
        except Exception as exc:
            self.query_one("#edit-status", Static).update(f"error: {exc}")

    def _collect_field(self, name: str, spec: dict):
        kind = spec["type"]
        if kind == "enum":
            sel = self.query_one(f"#edit-{name}", Select)
            if not isinstance(sel.value, str):
                raise _Skip
            return sel.value
        if kind == "set":
            add_raw = self.query_one(f"#edit-{name}-add", Input).value
            rm_raw = self.query_one(f"#edit-{name}-rm", Input).value
            add = [v.strip() for v in add_raw.split(",") if v.strip()]
            remove = [v.strip() for v in rm_raw.split(",") if v.strip()]
            if not add and not remove:
                raise _Skip
            ops = {}
            if add:
                ops["add"] = add
            if remove:
                ops["remove"] = remove
            return ops
        raw = self.query_one(f"#edit-{name}", Input).value.strip()
        if not raw:
            raise _Skip
        if kind == "number":
            return float(raw) if "." in raw else int(raw)
        if kind == "bool":
            if raw.lower() in ("true", "1", "yes"):
                return True
            if raw.lower() in ("false", "0", "no"):
                return False
        return raw

    # --- events ----------------------------------------------------------------

    async def action_dismiss_or_back(self) -> None:
        if self._editing:
            await self._exit_edit()
        else:
            self.app.pop_screen()

    async def on_key(self, event) -> None:
        if not self._ready:
            return
        if self._editing:
            return  # let widgets handle input; esc handled by binding
        if isinstance(self.focused, Input):
            return
        if event.character == "r" and self._reading == "document":
            event.stop()
            await self._toggle_doc_mode()
            return
        if (self._reading == "document" and self._doc_mode == "chunks"
                and event.key in ("j", "k") and self._chunks):
            event.stop()
            cl = self.query_one("#chunk-list", OptionList)
            cur = cl.highlighted if cl.highlighted is not None else 0
            cl.highlighted = max(0, min(cur + (1 if event.key == "j" else -1),
                                        len(self._chunks) - 1))
            return
        binding = self._by_key.get(event.key)
        if binding is None:
            return
        event.stop()
        if binding.capability == "filter":
            if self._reading == "document" and self._doc_mode == "chunks":
                self.query_one("#chunk-filter", Input).focus()
        elif binding.capability == "open-artifact":
            await self._open_original()
        elif binding.capability == "assert":
            await self._enter_edit()

    async def on_button_pressed(self, event) -> None:
        if event.button.id == "edit-save":
            await self._save_edit()

    async def on_option_list_option_highlighted(self, event) -> None:
        if not self._ready:
            return
        if event.option_list.id == "field-list":
            self._show_field(self._fields_order[event.option_index])
        elif event.option_list.id == "chunk-list":
            self.select_chunk(event.option_index)

    async def on_input_submitted(self, event) -> None:
        if self._editing:
            await self._save_edit()
            return
        if event.input.id == "chunk-filter":
            self.apply_chunk_filter(event.value.strip())
            self.query_one("#chunk-list", OptionList).focus()

    async def _open_original(self) -> None:
        try:
            path = await self.client.doc_path(self.doc_id, "original")
        except httpx.HTTPStatusError as exc:
            self.query_one("#inspector", RendStatic).update(
                f"original unavailable ({exc.response.status_code})")
            return
        if path is None:
            self.query_one("#inspector", RendStatic).update("original unavailable (bytes gone)")
            return
        reveal(path)


class _Skip(Exception):
    """Field was not edited — skip it."""
