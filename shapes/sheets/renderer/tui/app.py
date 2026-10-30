import json
import shutil
from datetime import datetime
from pathlib import Path

import yaml
import requests

from textual.app import App, ComposeResult
from textual.design import ColorSystem
from textual.theme import Theme
from textual.widgets import DataTable, Header, Footer, Static, Label, Input, TextArea, OptionList
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import work

from shapes.sheets.src.fields import parse_fields

_DEFAULT_TCSS = Path(__file__).parent / "app.tcss"

RUNTIME_RESERVED_KEYS = {"q", "r", "?", "escape", "up", "down", "left", "right"}

# Capabilities the runtime exposes to field actions.
# The sheet declares action: open on a field.
# The runtime knows what "open" means.
RUNTIME_ACTIONS = {
    "open": lambda value: __import__("webbrowser").open(value),
}

SHEETS_THEME = Theme(
    name="sheets-dark",
    dark=True,
    primary="#00d4aa",
    secondary="#005f5f",
    accent="#00d4aa",
    foreground="#e8e8e8",
    background="#000000",
    surface="#000000",
    panel="#1a1a1a",
    error="#ff4444",
    success="#00d4aa",
    warning="#ffa62b",
    text_alpha=1.0,
)


class ActionModal(ModalScreen):
    """Modal for capturing user input for a pipeline action.

    Three modes:
    - options: OptionList for enum fields (user picks from list)
    - input: single-line Input (enter to submit)
    - textarea: multiline TextArea (shift+enter to submit)
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("shift+enter", "submit", "Submit"),
        Binding("alt+enter", "submit", "Submit"),
    ]

    def __init__(
        self,
        kind: str,
        description: str,
        use_textarea: bool = False,
        options: list[str] | None = None,
    ):
        super().__init__()
        self._kind = kind
        self._description = description
        self._use_textarea = use_textarea
        self._options = options

    def compose(self) -> ComposeResult:
        with Static(id="action-modal"):
            yield Label(f"{self._kind}: {self._description}")
            if self._options:
                yield OptionList(*self._options, id="modal-options")
            elif self._use_textarea:
                yield TextArea(id="modal-input")
                yield Label("shift+enter submit | esc cancel")
            else:
                yield Input(placeholder="Enter value, press enter...", id="modal-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.prompt))

    def action_submit(self) -> None:
        if self._use_textarea:
            value = self.query_one(TextArea).text.strip()
            self.dismiss(value)
        elif not self._options:
            value = self.query_one(Input).value.strip()
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen):
    """Modal showing all keybindings."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("question_mark", "close", "Close"),
    ]

    def __init__(self, help_text: str):
        super().__init__()
        self._help_text = help_text

    def compose(self) -> ComposeResult:
        with Static(id="help-screen"):
            yield Static(self._help_text)

    def action_close(self) -> None:
        self.dismiss(None)


class SearchModal(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Static(id="action-modal"):
            yield Label("Search:")
            yield Input(placeholder="Type to filter...", id="search-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SheetsApp(App):
    CSS = _DEFAULT_TCSS.read_text()

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self, sheet_dir: Path, api_url: str = "http://127.0.0.1:4200"):
        super().__init__()
        self.register_theme(SHEETS_THEME)
        self.theme = "sheets-dark"
        self.sheet_dir = Path(sheet_dir)
        self.api_url = api_url
        self.sheet = yaml.safe_load((self.sheet_dir / "sheet.yaml").read_text())
        self.title = self.sheet.get("title", "sheets")
        self._fields = parse_fields(self.sheet)
        self._field_map = {f.name: f for f in self._fields}
        self._row_key_list: list[str] = []
        self._on_processed_set = False
        self._keys = self.sheet.get("keys") or {}
        self._reserved_keys = RUNTIME_RESERVED_KEYS | set(self._keys.values())
        self._pipeline_actions = self._read_pipeline_actions()
        self._boolean_toggles = self._read_boolean_toggles()
        self._visibility_field = self.sheet.get("view", {}).get("visibility_field")
        self._show_hidden = False
        self._search_query = ""
        self._connected = True

    def set_watcher_callback(self) -> None:
        """Mark that the watcher has a callback wired. No staggered refreshes needed."""
        self._on_processed_set = True

    def _read_pipeline_actions(self) -> dict[str, dict]:
        """Reads pipeline inputs from sheet.yaml and builds key -> action map."""
        actions = {}
        pipeline = self.sheet.get("pipeline", {})
        inputs = pipeline.get("inputs", {})
        for kind, spec in inputs.items():
            key = spec.get("key")
            if not key:
                continue
            if key in self._reserved_keys:
                raise ValueError(f"Pipeline input '{kind}' declares key '{key}' which is reserved")
            if key in actions:
                raise ValueError(f"Pipeline input '{kind}' declares key '{key}' which is already used")
            actions[key] = {
                "kind": kind,
                "description": spec.get("description", kind),
                "context": spec.get("context", {}),
                "bypass_inference": spec.get("bypass_inference", False),
            }
        return actions

    def _read_boolean_toggles(self) -> dict:
        """Read boolean fields with key: declarations."""
        toggles = {}
        for field in self._fields:
            if field.type == "boolean" and field.key:
                if field.key in self._reserved_keys:
                    raise ValueError(f"Field '{field.name}' declares key '{field.key}' which is reserved")
                if field.key in self._pipeline_actions:
                    raise ValueError(f"Field '{field.name}' declares key '{field.key}' which is used by pipeline input")
                if field.key in toggles:
                    raise ValueError(f"Field '{field.name}' declares key '{field.key}' which is already used by another toggle")
                toggles[field.key] = field
        return toggles

    def _build_help_text(self) -> str:
        lines = []
        lines.append("Keybindings")
        lines.append("-" * 40)
        if self._boolean_toggles:
            for key, field in sorted(self._boolean_toggles.items()):
                lines.append(f"  {key}    {field.label:<12} Toggle {field.name}")
            lines.append("")
        for key, action in sorted(self._pipeline_actions.items()):
            ctx = action["context"]
            ctx_str = " (row)" if ctx.get("row_id") else ""
            if ctx.get("cell"):
                ctx_str = " (cell)"
            lines.append(f"  {key}    {action['kind']:<12} {action['description']}{ctx_str}")
        lines.append("")
        keys = self._keys
        if keys.get("view"):
            lines.append(f"  {keys['view']}    View row detail")
        if keys.get("open"):
            lines.append(f"  {keys['open']}    Open (field action)")
        if keys.get("toggle_hidden"):
            lines.append(f"  {keys['toggle_hidden']}    Toggle hidden rows")
        if keys.get("search"):
            lines.append(f"  {keys['search']}    Search")
        lines.append("  ?    Help")
        lines.append("  r    Refresh")
        lines.append("  q    Quit")
        lines.append("")
        lines.append("  shift+enter to submit  |  esc to cancel")
        return "\n".join(lines)

    def _write_inbox_file(self, kind: str, context: dict, content: str) -> None:
        """Write to staging/ then atomic-move to inbox/."""
        staging = self.sheet_dir / "ingest" / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        inbox = self.sheet_dir / "ingest" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        filename = f"{timestamp}-from-tui.txt"
        if context:
            ctx_str = " ".join(f"{k}={v}" for k, v in context.items())
            header = f"{kind} {ctx_str}"
        else:
            header = kind

        tmp = staging / filename
        tmp.write_text(f"{header}\n{content}\n")
        shutil.move(str(tmp), str(inbox / filename))

    def _get_columns(self) -> list[str]:
        return [f.name for f in self._fields]

    def _format_cell_value(self, value, field) -> str:
        """Format a cell value for table display. Dispatches on field type."""
        if field and field.type == "log":
            if not value:
                return ""
            try:
                entries = json.loads(value)
                if not entries:
                    return ""
                latest = entries[-1].get("text", "")
                count = len(entries)
                return f"{count} | {latest}"
            except (ValueError, TypeError):
                return str(value) if value else ""
        return str(value) if value else ""

    def _build_status_text(
        self, row_count: int, inbox_count: int, failed_count: int,
        hidden_count: int = 0,
    ) -> str:
        parts = [f"{row_count} rows"]
        if hidden_count and not self._show_hidden:
            parts.append(f"hiding {hidden_count}")
        elif hidden_count and self._show_hidden:
            parts.append(f"showing all ({hidden_count} hidden)")
        if inbox_count:
            parts.append(f"{inbox_count} pending")
        if failed_count:
            parts.append(f"{failed_count} failed")
        if self._search_query:
            parts.append(f'"{self._search_query}"')
        key_hints = " ".join(
            f"{k}={a['kind'].lower()}" for k, a in self._pipeline_actions.items()
        )
        toggle_hints = " ".join(
            f"{k}={f.label}" for k, f in self._boolean_toggles.items()
        )
        keys = self._keys
        cap_hints = []
        if keys.get("view"):
            cap_hints.append(f"{keys['view']}=view")
        if keys.get("open"):
            cap_hints.append(f"{keys['open']}=open")
        if keys.get("toggle_hidden"):
            cap_hints.append(f"{keys['toggle_hidden']}=hidden")
        if keys.get("search"):
            cap_hints.append(f"{keys['search']}=search")
        cap_str = " ".join(cap_hints)
        parts.append(f"{key_hints} {toggle_hints} {cap_str} ?=help q=quit")
        return " | ".join(parts)

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(zebra_stripes=True, cell_padding=2)
        yield Static(self._build_status_text(0, 0, 0), id="status")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for field in self._fields:
            table.add_column(field.label, key=field.name)
        self._load_rows()
        self.set_interval(5, self._load_rows)

    # Map from sheet.keys capability names to action methods
    _CAPABILITY_ACTIONS = {
        "view": "action_view_row",
        "open": "action_open_url",
        "toggle_hidden": "action_toggle_hidden",
        "search": "action_search",
    }

    def on_key(self, event) -> None:
        key = event.key
        char = event.character
        if not self._connected:
            return

        # Renderer capabilities — dispatched from sheet.keys
        for cap, declared_char in self._keys.items():
            if (char == declared_char or key == declared_char) and cap in self._CAPABILITY_ACTIONS:
                event.stop()
                getattr(self, self._CAPABILITY_ACTIONS[cap])()
                return

        # Pipeline inputs and boolean toggles — from declaration
        if key in self._pipeline_actions:
            event.stop()
            self._trigger_action(self._pipeline_actions[key])
        elif key in self._boolean_toggles:
            event.stop()
            self._toggle_boolean(self._boolean_toggles[key])

    def toggle_boolean_for_row(self, row_id: str, field, current_value: str) -> None:
        """Toggle a boolean field. Shared by table and detail view."""
        new_value = "false" if current_value.lower() in ("true", "1") else "true"
        body = f"{field.name} = {new_value}"
        self._write_inbox_file("SET", {"row_id": row_id}, body)
        if not self._on_processed_set:
            self.set_timer(0.2, self._load_rows)
            self.set_timer(0.8, self._load_rows)

    def _toggle_boolean(self, field) -> None:
        table = self.query_one(DataTable)
        cursor_row = table.cursor_coordinate.row
        if cursor_row >= len(self._row_key_list):
            self._show_error("No row selected")
            return
        row_id = self._row_key_list[cursor_row]
        try:
            current = str(table.get_cell(row_id, field.name)).strip().lower()
        except Exception:
            current = ""
        self.toggle_boolean_for_row(row_id, field, current)

    def _resolve_modal_mode(self, field) -> dict:
        """Map a field's type to modal configuration. Shared by table and detail view.

        Returns: {"use_textarea": bool, "options": list[str] | None}
        """
        if field and field.type == "log":
            return {"use_textarea": True, "options": None, "is_log": True}
        elif field and field.type == "enum" and field.values:
            return {"use_textarea": False, "options": field.values}
        elif field and field.type == "boolean":
            return {"use_textarea": False, "options": ["true", "false"]}
        elif field and field.type == "text":
            return {"use_textarea": True, "options": None}
        elif field:
            return {"use_textarea": False, "options": None}
        else:
            return {"use_textarea": True, "options": None}

    def edit_field(self, row_id: str, field, kind: str = "SET",
                   description: str = "", on_done=None) -> None:
        """Open the right modal for a field and write the result to inbox.

        Called by both the table (via _trigger_action) and the detail view.
        Log fields write an append op instead of a SET.
        """
        mode = self._resolve_modal_mode(field)
        label = field.label if field else description

        # Log fields: find the append pipeline input for this field
        if mode.get("is_log") and field:
            append_handler = None
            for _key, action in self._pipeline_actions.items():
                handler = self.sheet["pipeline"]["inputs"].get(action["kind"], {})
                if handler.get("op") == "append" and handler.get("target_field") == field.name:
                    append_handler = action
                    break

            def handle_log_result(value):
                if value is None or value == "":
                    return
                self._write_inbox_file(
                    append_handler["kind"] if append_handler else "LOG",
                    {"row_id": row_id},
                    value,
                )
                if not self._on_processed_set:
                    self.set_timer(0.2, self._load_rows)
                    self.set_timer(0.8, self._load_rows)
                if on_done:
                    on_done()

            self.push_screen(
                ActionModal("LOG", label, use_textarea=True),
                handle_log_result,
            )
            return

        def handle_result(value):
            if value is None or value == "":
                return
            if field:
                body = f"{field.name} = {value}"
            else:
                body = value
            self._write_inbox_file(kind, {"row_id": row_id} if row_id else {}, body)
            if not self._on_processed_set:
                self.set_timer(0.2, self._load_rows)
                self.set_timer(0.8, self._load_rows)
                self.set_timer(2.0, self._load_rows)
            if on_done:
                on_done()

        self.push_screen(
            ActionModal(kind, label, use_textarea=mode["use_textarea"], options=mode["options"]),
            handle_result,
        )

    def _trigger_action(self, action: dict) -> None:
        kind = action["kind"]
        description = action["description"]
        context_spec = action["context"]
        resolved_context = {}

        cell_field_name = None
        cell_field = None
        if context_spec:
            table = self.query_one(DataTable)
            cursor_row = table.cursor_coordinate.row

            if "row_id" in context_spec:
                if cursor_row < len(self._row_key_list):
                    resolved_context["row_id"] = self._row_key_list[cursor_row]
                else:
                    self._show_error("No row selected")
                    return

            if "cell" in context_spec:
                cursor_col = table.cursor_coordinate.column
                columns = self._get_columns()
                if cursor_col < len(columns):
                    cell_field_name = columns[cursor_col]
                    cell_field = next(
                        (f for f in self._fields if f.name == cell_field_name), None
                    )
                else:
                    self._show_error("No cell selected")
                    return

        row_id = resolved_context.get("row_id")

        if cell_field:
            self.edit_field(row_id, cell_field, kind=kind)
        else:
            # Freeform action (NEW, FETCH, UPDATE) — no specific field
            mode = self._resolve_modal_mode(None)
            label = description

            def handle_result(value):
                if value is None or value == "":
                    return
                self._write_inbox_file(kind, resolved_context, value)
                if not self._on_processed_set:
                    self.set_timer(0.2, self._load_rows)
                    self.set_timer(0.8, self._load_rows)
                    self.set_timer(2.0, self._load_rows)

            self.push_screen(
                ActionModal(kind, label, use_textarea=mode["use_textarea"], options=mode["options"]),
                handle_result,
            )

    def action_open_url(self) -> None:
        """Run the declared action on the selected row.

        First checks the current cell. If it has an action, use it.
        Otherwise, find the first field with an action and use that.
        """
        table = self.query_one(DataTable)
        try:
            cursor = table.cursor_coordinate
            if cursor.row >= len(self._row_key_list):
                return
            row_key = self._row_key_list[cursor.row]
            columns = self._get_columns()

            # Try current cell first
            col_name = columns[cursor.column]
            field = next((f for f in self._fields if f.name == col_name), None)
            if field and field.action:
                value = self._get_cell_value(table, row_key, col_name)
                if value:
                    RUNTIME_ACTIONS[field.action](value)
                    return

            # Fall back to first field with an action
            for f in self._fields:
                if f.action:
                    value = self._get_cell_value(table, row_key, f.name)
                    if value:
                        RUNTIME_ACTIONS[f.action](value)
                        return

            self._show_error("No actionable field with a value")
        except Exception as e:
            self._show_error(str(e))

    def _get_cell_value(self, table, row_key: str, col_name: str) -> str | None:
        """Get a cell value, returning None for empty/None values."""
        try:
            value = table.get_cell(row_key, col_name)
            if value is None:
                return None
            value = str(value).strip()
            return value if value and value != "None" else None
        except Exception:
            return None

    def action_help(self) -> None:
        self.push_screen(HelpScreen(self._build_help_text()))

    def action_view_row(self) -> None:
        """Open the detail view for the selected row."""
        table = self.query_one(DataTable)
        cursor_row = table.cursor_coordinate.row
        if cursor_row >= len(self._row_key_list):
            self._show_error("No row selected")
            return
        row_id = self._row_key_list[cursor_row]

        # Fetch current row data from API
        try:
            resp = requests.get(f"{self.api_url}/api/rows/{row_id}", timeout=5)
            resp.raise_for_status()
            row_data = resp.json()
        except Exception as e:
            self._show_error(str(e))
            return

        from shapes.sheets.renderer.tui.detail import DetailView
        view_config = self.sheet.get("view")
        detail = DetailView(
            row_data=row_data,
            row_id=row_id,
            fields=self._fields,
            view_config=view_config,
            pipeline_actions=self._pipeline_actions,
            boolean_toggles=self._boolean_toggles,
            runtime_actions=RUNTIME_ACTIONS,
        )
        self.push_screen(detail, callback=lambda _: self._load_rows())

    def action_toggle_hidden(self) -> None:
        self._show_hidden = not self._show_hidden
        self._load_rows()

    def action_search(self) -> None:
        if self._search_query:
            self._search_query = ""
            self._load_rows()
            return
        self.push_screen(SearchModal(), callback=self._apply_search)

    def _apply_search(self, query) -> None:
        if query is None:
            return
        self._search_query = query.strip()
        self._load_rows()

    @work(thread=True)
    def _load_rows(self) -> None:
        try:
            resp = requests.get(f"{self.api_url}/api/rows", timeout=5)
            resp.raise_for_status()
            rows = resp.json()
        except Exception as e:
            self.call_from_thread(self._show_disconnected, str(e))
            return

        inbox_count = self._count_dir(self.sheet_dir / "ingest" / "inbox")
        failed_count = self._count_dir(
            self.sheet_dir / "ingest" / "failed", skip_error_files=True
        )
        self.call_from_thread(self._sync_table, rows, inbox_count, failed_count)

    def _count_dir(self, path: Path, skip_error_files: bool = False) -> int:
        if not path.exists():
            return 0
        files = [
            f for f in path.iterdir()
            if f.is_file() and not f.name.startswith(".")
        ]
        if skip_error_files:
            files = [f for f in files if not f.name.endswith(".error")]
        return len(files)

    def _show_disconnected(self, message: str) -> None:
        """API is unreachable. Clear table, block actions, show error."""
        self._connected = False
        table = self.query_one(DataTable)
        table.clear()
        self._row_key_list = []
        status = self.query_one("#status", Static)
        status.update(f"DISCONNECTED: {message} | r=retry q=quit")
        status.add_class("has-errors")

    def _show_error(self, message: str) -> None:
        status = self.query_one("#status", Static)
        status.update(f"ERROR: {message}")
        status.add_class("has-errors")

    def _sync_table(
        self, rows: list[dict], inbox_count: int, failed_count: int
    ) -> None:
        self._connected = True
        table = self.query_one(DataTable)
        columns = self._get_columns()

        # Count hidden
        hidden_count = 0
        if self._visibility_field:
            hidden_count = sum(1 for r in rows if str(r.get(self._visibility_field, "")).lower() in ("true", "1"))

        # Filter hidden
        if self._visibility_field and not self._show_hidden:
            vf = self._visibility_field
            visible_rows = [r for r in rows if str(r.get(vf, "")).lower() not in ("true", "1")]
        else:
            visible_rows = rows

        # Apply search
        if self._search_query:
            q = self._search_query.lower()
            visible_rows = [
                r for r in visible_rows
                if any(q in str(v).lower() for v in r.values() if v)
            ]

        incoming_keys = []
        incoming_keys_set = set()
        for row in visible_rows:
            key = row.get("id", "")
            incoming_keys.append(key)
            incoming_keys_set.add(key)
            values = [
                self._format_cell_value(row.get(col), self._field_map.get(col))
                for col in columns
            ]

            if key in set(self._row_key_list):
                for i, col in enumerate(columns):
                    try:
                        table.update_cell(key, col, values[i])
                    except Exception:
                        pass
            else:
                table.add_row(*values, key=key)

        for old_key in set(self._row_key_list) - incoming_keys_set:
            try:
                table.remove_row(old_key)
            except Exception:
                pass

        self._row_key_list = incoming_keys

        status = self.query_one("#status", Static)
        status.update(self._build_status_text(
            len(visible_rows), inbox_count, failed_count, hidden_count=hidden_count
        ))
        if failed_count:
            status.add_class("has-errors")
        else:
            status.remove_class("has-errors")

    def action_refresh(self) -> None:
        self._load_rows()
