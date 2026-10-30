"""Detail view screen — shows one row's fields in a readable layout.

Reads the view: block from sheet.yaml for section layout.
Delegates editing to the app's shared edit_field() method.
No editing logic lives here — the detail view is a display + cursor.
"""

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, Label
from textual.binding import Binding


class DetailView(ModalScreen):
    """Full-screen detail view for a single row.

    All editing is delegated to self.app.edit_field() and
    self.app._toggle_boolean() — the same code paths the table uses.
    """

    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
    ]

    def __init__(
        self,
        row_data: dict,
        row_id: str,
        fields: list,
        view_config: dict | None,
        pipeline_actions: dict,
        boolean_toggles: dict,
        runtime_actions: dict,
    ):
        super().__init__()
        self.row_data = row_data
        self.row_id = row_id
        self._fields = fields
        self._field_map = {f.name: f for f in fields}
        self._view_config = view_config or {}
        self._pipeline_actions = pipeline_actions
        self._boolean_toggles = boolean_toggles
        self._runtime_actions = runtime_actions
        self._cursor_index = 0
        self._field_order = self._compute_field_order()

    def _compute_field_order(self) -> list[str]:
        """Compute which fields to show and in what order. Done in __init__,
        not compose(), so field_order is available before the UI renders."""
        sections = self._view_config.get("sections", [])
        notes_field = self._view_config.get("notes_field")
        order = []

        if sections:
            declared = set()
            for section in sections:
                flist = section.get("fields", [])
                if notes_field:
                    flist = [f for f in flist if f != notes_field]
                declared.update(flist)
                order.extend(flist)

            uncategorized = [
                f.name for f in self._fields
                if f.name not in declared
                and f.name != notes_field
                and f.type != "primary"
            ]
            order.extend(uncategorized)
        else:
            order = [f.name for f in self._fields if f.type != "primary"]

        if notes_field and notes_field in self._field_map:
            order.append(notes_field)

        return order

    def compose(self) -> ComposeResult:
        sections = self._view_config.get("sections", [])
        notes_field = self._view_config.get("notes_field")

        with VerticalScroll(id="detail-view"):
            yield Label(f"  {self.row_id}", id="detail-title")

            if sections:
                declared_fields = set()
                for section in sections:
                    fields_in_section = section.get("fields", [])
                    if notes_field:
                        fields_in_section = [f for f in fields_in_section if f != notes_field]
                    declared_fields.update(fields_in_section)

                    yield Label(f"\n  [{section['label']}]", classes="section-header")
                    for fname in fields_in_section:
                        yield self._render_field(fname)

                uncategorized = [
                    f.name for f in self._fields
                    if f.name not in declared_fields
                    and f.name != notes_field
                    and f.type != "primary"
                ]
                if uncategorized:
                    yield Label("\n  [Other]", classes="section-header")
                    for fname in uncategorized:
                        yield self._render_field(fname)
            else:
                for field in self._fields:
                    if field.type != "primary":
                        yield self._render_field(field.name)

            if notes_field and notes_field in self._field_map:
                nf = self._field_map[notes_field]
                value = str(self.row_data.get(notes_field, "") or "")
                yield Label(f"\n  [{nf.label}]", classes="section-header")
                yield Static(f"  {value or '(empty)'}", id=f"field-{notes_field}", classes="detail-notes")

            yield Static("", id="detail-status")

    def _render_field(self, fname: str) -> Static:
        field = self._field_map.get(fname)
        if not field:
            return Static(f"  {fname}: ???")

        value = self.row_data.get(fname, "")

        # Log fields render as timeline
        if field.type == "log":
            return self._render_log_field(fname, field, value)

        display_value = str(value) if value else "(empty)"

        hints = []
        if field.action and field.action in self._runtime_actions:
            hints.append("o=open")
        if field.type == "boolean" and field.key:
            hints.append(f"{field.key}=toggle")

        hint_str = f"  [{', '.join(hints)}]" if hints else ""

        return Static(
            f"  {field.label:<20} {display_value}{hint_str}",
            id=f"field-{fname}",
            classes="detail-field",
        )

    def _render_log_field(self, fname: str, field, value) -> Static:
        import json as _json
        try:
            entries = _json.loads(value) if value else []
        except (ValueError, TypeError):
            entries = []

        if not entries:
            return Static(f"  {field.label:<20} (no entries)", id=f"field-{fname}", classes="detail-field")

        lines = [f"  {field.label}"]
        for entry in entries:
            ts = entry.get("ts", "")[:16]
            by = f"@{entry['by']}" if entry.get("by") else ""
            text = entry.get("text", "")
            lines.append(f"    {ts}  {by:<12} {text}")

        return Static("\n".join(lines), id=f"field-{fname}", classes="detail-field")

    def on_mount(self) -> None:
        self._update_cursor()
        self._update_status()

    def on_key(self, event) -> None:
        key = event.key
        field = self.current_field

        # Pipeline action keys (e for edit, l for log, etc.)
        if key in self._pipeline_actions:
            event.stop()
            action = self._pipeline_actions[key]
            ctx = action.get("context", {})

            if ctx.get("cell") and field:
                # Cell-level action (e.g., SET/edit) — use current field
                self.app.edit_field(
                    self.row_id, field, kind=action["kind"],
                    on_done=lambda: self.dismiss(None),
                )
            elif ctx.get("row_id"):
                # Row-level action (e.g., UPDATE/log) — freeform text
                mode = self.app._resolve_modal_mode(None)
                from shapes.sheets.renderer.tui.app import ActionModal
                def handle_result(value):
                    if value is None or value == "":
                        return
                    self.app._write_inbox_file(action["kind"], {"row_id": self.row_id}, value)
                    self.dismiss(None)
                self.app.push_screen(
                    ActionModal(action["kind"], action["description"],
                                use_textarea=mode["use_textarea"], options=mode["options"]),
                    handle_result,
                )
            return

        # Boolean toggle keys
        if key in self._boolean_toggles:
            event.stop()
            toggle_field = self._boolean_toggles[key]
            current = str(self.row_data.get(toggle_field.name, "")).lower()
            self.app.toggle_boolean_for_row(self.row_id, toggle_field, current)
            self.dismiss(None)
            return

        # Open action
        if key == "o" and field and field.action and field.action in self._runtime_actions:
            event.stop()
            value = str(self.row_data.get(field.name, "") or "").strip()
            if value:
                self._runtime_actions[field.action](value)
            return

    def _update_cursor(self) -> None:
        for i, fname in enumerate(self._field_order):
            widget = self.query_one(f"#field-{fname}", Static)
            if i == self._cursor_index:
                widget.add_class("detail-cursor")
            else:
                widget.remove_class("detail-cursor")

    def _update_status(self) -> None:
        if not self._field_order:
            return
        field = self.current_field
        parts = []
        for key, action in self._pipeline_actions.items():
            ctx = action.get("context", {})
            if ctx.get("cell") and field:
                parts.append(f"{key}={action['description']}")
            elif ctx.get("row_id") and not ctx.get("cell"):
                parts.append(f"{key}={action['description']}")
        if field and field.action:
            parts.append("o=open")
        if field and field.type == "boolean" and field.key:
            parts.append(f"{field.key}=toggle")
        parts.append("esc=back")
        status = self.query_one("#detail-status", Static)
        status.update("  " + " | ".join(parts))

    def action_cursor_up(self) -> None:
        if self._cursor_index > 0:
            self._cursor_index -= 1
            self._update_cursor()
            self._update_status()

    def action_cursor_down(self) -> None:
        if self._cursor_index < len(self._field_order) - 1:
            self._cursor_index += 1
            self._update_cursor()
            self._update_status()

    def action_close(self) -> None:
        self.dismiss(None)

    @property
    def current_field_name(self) -> str | None:
        if not self._field_order:
            return None
        return self._field_order[self._cursor_index]

    @property
    def current_field(self):
        name = self.current_field_name
        return self._field_map.get(name) if name else None
