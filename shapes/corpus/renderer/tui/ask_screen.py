# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""AskScreen — compose a scoped RAG query, run it, render the answer, and save it.
A dumb renderer: it gathers the form, calls ask_runner (the CLI seam), and shows
the record via the shared formatter. No corpus logic lives here. Defaults match
the requirement: grounding 1.0, hybrid, no filter. Save is offered only once an
answer exists — below the answer, where a reader decides it is worth keeping."""
import re
import unicodedata
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (Button, Input, Label, LoadingIndicator, OptionList,
                             Select, Static)
from textual.widgets.option_list import Option

from shapes.corpus.commands._access_cli import (format_answer, format_passages,
                                                format_provenance)
from shapes.corpus.renderer.tui import ask_runner

_MODES = [("hybrid", "hybrid"), ("vector", "vector"),
          ("lexical", "lexical"), ("none", "none")]


class _Pane(VerticalScroll):
    """A scroll pane that takes focus, so its content scrolls with the keyboard
    (↑/↓, PgUp/PgDn, Home/End) — not only the mouse wheel."""
    can_focus = True


def slug(text: str) -> str:
    """A filename stem from a question: ascii, lowercase, dash-separated."""
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", norm.lower())).strip("-")[:60].strip("-")


class AskScreen(Screen):
    CSS = """
    /* Three planes, the catalogue frame's widths: rail 24 · form 40 · response 1fr. */
    #ask-saved-pane { width: 24; border-right: tall $panel-darken-1; padding: 1; }
    #ask-form { width: 40; border-right: tall $panel-darken-1; padding: 0 1; }
    #ask-response { width: 1fr; padding: 0 1; }
    .field-label { color: $text-muted; height: 1; }
    #ask-form Input, #ask-form Select { margin-bottom: 1; }
    .hidden { display: none; }
    #ask-loading { height: 1; color: $accent; }
    #ask-result-scroll { height: 1fr; border: round $panel; padding: 0 1; }
    #ask-save-row { height: auto; margin-top: 1; }
    #ask-name { width: 1fr; }
    #ask-details-panel { height: 45%; border: round $panel; padding: 0 1; }
    #ask-result-scroll:focus, #ask-details-panel:focus { border: round $accent; }
    #ask-hint { dock: bottom; height: 1; color: $text-muted; padding: 0 1; }
    """
    # PgUp/PgDn scroll the answer from anywhere on the screen. A focused scroll
    # pane (the details panel) consumes these first via its own bindings, so this
    # only fires the answer scroll when focus is on the form or the saved list.
    BINDINGS = [
        ("escape", "app.pop_screen", "back"),
        ("pageup", "scroll_answer(-1)", "scroll answer"),
        ("pagedown", "scroll_answer(1)", "scroll answer"),
    ]

    def action_scroll_answer(self, direction: int) -> None:
        pane = self.query_one("#ask-result-scroll", _Pane)
        (pane.scroll_page_down if direction > 0 else pane.scroll_page_up)()

    def __init__(self, corpus_dir: Path, asks: list, ask_defaults: dict | None = None):
        super().__init__()
        self.corpus_dir = corpus_dir
        self.asks = asks
        # id -> {grounding, mode}: each ask's DECLARED retrieval defaults, so the form
        # follows the ask instead of imposing one universal 1.0/hybrid. Absent → the
        # engine's own fallbacks (1.0, hybrid), which is what a plain RAG ask expects.
        self._ask_defaults: dict = ask_defaults or {}
        self._record: dict | None = None        # last run's record, for save-with-result
        self._saved_by_name: dict = {}
        # a saved query sets ask + its own grounding/mode; suppress the one ask-change
        # sync that its ask switch would otherwise fire, so the saved values stand.
        self._suppress_ask_sync = False

    def _declared(self, ask_id: str) -> tuple[str, str]:
        d = self._ask_defaults.get(ask_id, {})
        return str(float(d.get("grounding", 1.0))), d.get("mode", "hybrid")

    def compose(self) -> ComposeResult:
        default_ask = "answer" if "answer" in self.asks else (self.asks[0] if self.asks else "")
        init_grounding, init_mode = self._declared(default_ask)
        with Horizontal(id="ask-body"):
            with Vertical(id="ask-saved-pane"):
                yield Label("Saved queries", classes="field-label")
                yield OptionList(id="ask-saved")
            with Vertical(id="ask-form"):
                yield Label("ask", classes="field-label")
                yield Select([(a, a) for a in self.asks], value=default_ask,
                             id="ask-which", allow_blank=False)
                yield Label("question", classes="field-label")
                yield Input(placeholder="your question", id="ask-question")
                yield Label("grounding (0.0 model → 1.0 passages)", classes="field-label")
                yield Input(value=init_grounding, id="ask-grounding")
                yield Label("retrieval mode", classes="field-label")
                yield Select(_MODES, value=init_mode, id="ask-mode", allow_blank=False)
                yield Label("where filter (optional)", classes="field-label")
                yield Input(placeholder="e.g. visibility == general", id="ask-where")
                yield Button("Run", id="ask-run", variant="primary")
                yield LoadingIndicator(id="ask-loading")
            with Vertical(id="ask-response"):
                with _Pane(id="ask-result-scroll"):
                    yield Static("", id="ask-result")
                with Horizontal(id="ask-save-row", classes="hidden"):
                    yield Input(placeholder="save as… (defaults to a slug of the question)",
                                id="ask-name")
                    yield Button("Save", id="ask-save-result", variant="success")
                    yield Button("Details", id="ask-details")
                with _Pane(id="ask-details-panel", classes="hidden"):
                    yield Static("", id="ask-details-text")
        yield Static("PgUp/PgDn: scroll the answer   tab: move between panels   esc: back",
                     id="ask-hint")

    async def on_mount(self) -> None:
        self.query_one("#ask-loading").display = False          # spinner shows only while running
        await self._refresh_saved()

    # --- form -> definition ------------------------------------------------
    def _definition(self) -> dict:
        grounding = float(self.query_one("#ask-grounding", Input).value)
        if not (0.0 <= grounding <= 1.0):
            raise ValueError("grounding out of range")
        return {
            "ask": self.query_one("#ask-which", Select).value,
            "question": self.query_one("#ask-question", Input).value.strip(),
            "grounding": grounding,
            "mode": self.query_one("#ask-mode", Select).value,
            "where": self.query_one("#ask-where", Input).value.strip() or None,
        }

    def _save_name(self, definition: dict) -> str:
        return self.query_one("#ask-name", Input).value.strip() or slug(definition["question"])

    def _result(self, text: str) -> None:
        self.query_one("#ask-result", Static).update(text)

    def _loading(self, on: bool) -> None:
        self.query_one("#ask-loading").display = on

    # --- actions -----------------------------------------------------------
    async def run_query(self) -> None:
        self._record = None                       # a fresh run; never keep a stale result
        self.query_one("#ask-save-row").add_class("hidden")     # no save until there is an answer
        self.query_one("#ask-details-panel").add_class("hidden")  # collapse stale details
        try:
            d = self._definition()
        except ValueError:
            self._result("grounding must be a number in [0.0, 1.0]")
            return
        if not d["question"]:
            self._result("enter a question")
            return
        self._result("Asking the model… (retrieving passages, then writing the answer)")
        self._loading(True)
        try:
            record = await ask_runner.run_ask(
                self.corpus_dir, d["ask"], d["question"],
                grounding=d["grounding"], mode=d["mode"], where=d["where"] or "")
        except RuntimeError as exc:
            self._result(str(exc))
            return
        finally:
            self._loading(False)
        self._record = record
        self._result(self._format_record(record))
        self.query_one("#ask-save-row").remove_class("hidden")  # answer is in — offer to keep it
        self.query_one("#ask-result-scroll").focus()            # so arrows/page keys scroll it

    async def save(self, *, definition_only: bool) -> None:
        try:
            d = self._definition()
        except ValueError:
            self._result("grounding must be a number in [0.0, 1.0]")
            return
        if not d["question"]:
            self._result("enter a question")
            return
        if not definition_only and (self._record is None or self._record.get("ask") != d["ask"]):
            self._result("run the query before saving its result")
            return
        try:
            path = await ask_runner.save_query(
                self.corpus_dir, self._save_name(d), d,
                record=self._record, definition_only=definition_only)
        except RuntimeError as exc:
            self._result(str(exc))
            return
        await self._refresh_saved()
        self._result(f"saved → {path}")

    async def _refresh_saved(self) -> None:
        saved = await ask_runner.list_queries(self.corpus_dir)
        lst = self.query_one("#ask-saved", OptionList)
        lst.clear_options()
        for item in saved:
            lst.add_option(Option(f"{item['name']}  ·  {item.get('question', '')}",
                                   id=item["name"]))
        self._saved_by_name = {item["name"]: item for item in saved}

    def _format_record(self, record: dict) -> str:
        return format_answer(record) if "answer" in record else format_passages(record["passages"])

    # --- events ------------------------------------------------------------
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ask-run":
            await self.run_query()
        elif event.button.id == "ask-save-result":
            await self.save(definition_only=False)
        elif event.button.id == "ask-details":
            self._toggle_details()

    def _toggle_details(self) -> None:
        panel = self.query_one("#ask-details-panel")
        if panel.has_class("hidden"):
            prov = (self._record or {}).get("provenance") or {}
            self.query_one("#ask-details-text", Static).update(format_provenance(prov))
            panel.remove_class("hidden")
            panel.focus()                      # focus so it scrolls with the keyboard at once
        else:
            panel.add_class("hidden")

    def on_select_changed(self, event: Select.Changed) -> None:
        # only the ask picker drives the sync; changing the mode Select is not an ask change
        if event.select.id != "ask-which":
            return
        if self._suppress_ask_sync:            # a saved-query load set its own values
            self._suppress_ask_sync = False
            return
        grounding, mode = self._declared(event.value)   # follow the newly chosen ask
        self.query_one("#ask-grounding", Input).value = grounding
        self.query_one("#ask-mode", Select).value = mode

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        item = self._saved_by_name[event.option.id]               # load definition into the form
        which = self.query_one("#ask-which", Select)
        if which.value != item["ask"]:         # suppress the sync this ask switch would fire,
            self._suppress_ask_sync = True     # so the saved grounding/mode below are not clobbered
            which.value = item["ask"]
        self.query_one("#ask-question", Input).value = item["question"]
        self.query_one("#ask-grounding", Input).value = str(item["grounding"])
        self.query_one("#ask-mode", Select).value = item["mode"]
        self.query_one("#ask-where", Input).value = item["where"] or ""
        self.query_one("#ask-name", Input).value = item["name"]
