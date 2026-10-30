# tests/test_corpus_tui_ask_screen.py
import pytest
from textual.app import App
from textual.widgets import Input, OptionList, Select, Static
from textual.widgets.option_list import Option

from shapes.corpus.renderer.tui import ask_runner
from shapes.corpus.renderer.tui.ask_screen import AskScreen, slug


class _Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen

    async def on_mount(self):
        await self.push_screen(self._screen)


def test_slug_makes_a_filename_stem():
    assert slug("¿Qué actitudes hay hacia la ESI?") == "que-actitudes-hay-hacia-la-esi"


@pytest.mark.asyncio
async def test_form_defaults_grounding_hybrid_no_where(tmp_path, monkeypatch):
    async def _none(corpus):
        return []
    monkeypatch.setattr(ask_runner, "list_queries", _none)   # on_mount must not shell out
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        assert scr.query_one("#ask-grounding", Input).value == "1.0"
        assert scr.query_one("#ask-mode", Select).value == "hybrid"
        assert scr.query_one("#ask-where", Input).value == ""
        assert scr.query_one("#ask-which", Select).value == "answer"   # defaults to answer


@pytest.mark.asyncio
async def test_run_renders_the_answer(tmp_path, monkeypatch):
    record = {"ask": "answer", "question": "¿q?", "answer": "Sí, hay apoyo. [aaaaaaaaaaaa:r1]",
              "passages": [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "esi",
                            "score": 0.4, "retriever": "hybrid", "span": [0, 3],
                            "name": "estudio-esi.md"}]}

    async def _fake_ask(corpus, ask_id, question, *, grounding, mode, where):
        return record

    async def _none(corpus):
        return []

    monkeypatch.setattr(ask_runner, "run_ask", _fake_ask)
    monkeypatch.setattr(ask_runner, "list_queries", _none)
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        scr.query_one("#ask-question", Input).value = "¿q?"
        await screen.run_query()
        await pilot.pause()
        rendered = scr.query_one("#ask-result", Static).content
        assert "Sí, hay apoyo." in str(rendered)


# ---- new tests added by code review fix ----

def test_slug_has_no_trailing_dash_after_truncation():
    # "palabra " repeated 20 times is 140 chars; after slug conversion it becomes
    # "palabra-" repeated which truncated at 60 chars can land on a dash.
    s = slug("palabra " * 20)
    assert not s.endswith("-")
    assert len(s) <= 60


@pytest.mark.asyncio
async def test_save_with_result_calls_save_query_with_record(tmp_path, monkeypatch):
    record = {"ask": "answer", "question": "¿q?", "answer": "Sí. [aaaaaaaaaaaa:r1]",
              "passages": [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "x",
                            "score": 0.4, "retriever": "hybrid", "span": [0, 1],
                            "name": "doc.md"}]}
    calls = {}

    async def _fake_ask(corpus, ask_id, question, *, grounding, mode, where):
        return record

    async def _fake_save(corpus, name, definition, *, record, definition_only):
        calls["record"] = record
        calls["definition_only"] = definition_only
        calls["name"] = name
        return "/tmp/queries/esi.md"

    async def _none(corpus):
        return []

    monkeypatch.setattr(ask_runner, "run_ask", _fake_ask)
    monkeypatch.setattr(ask_runner, "save_query", _fake_save)
    monkeypatch.setattr(ask_runner, "list_queries", _none)
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        pilot.app.screen.query_one("#ask-question", Input).value = "¿q?"
        await screen.run_query()
        await screen.save(definition_only=False)
        await pilot.pause()
        assert calls["definition_only"] is False
        assert calls["record"] == record
        assert "saved" in str(pilot.app.screen.query_one("#ask-result", Static).content)


@pytest.mark.asyncio
async def test_selecting_saved_item_loads_definition_into_form(tmp_path, monkeypatch):
    # OptionList.OptionSelected(option_list, option, index) per Textual 8.2.5 OptionMessage.__init__.
    # We build the real event using the public constructor to exercise the handler faithfully.
    item = {"name": "esi", "ask": "find", "question": "¿educación?",
            "grounding": 0.5, "mode": "vector", "where": "visibility == general"}

    async def _has_one(corpus):
        return [item]

    monkeypatch.setattr(ask_runner, "list_queries", _has_one)
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        lst = pilot.app.screen.query_one("#ask-saved", OptionList)
        option = lst.get_option_at_index(0)
        # Construct the real OptionSelected event: OptionList.OptionSelected(option_list, option, index)
        event = OptionList.OptionSelected(lst, option, 0)
        await screen.on_option_list_option_selected(event)
        await pilot.pause()
        s = pilot.app.screen
        assert s.query_one("#ask-which", Select).value == "find"
        assert s.query_one("#ask-question", Input).value == "¿educación?"
        assert s.query_one("#ask-grounding", Input).value == "0.5"
        assert s.query_one("#ask-mode", Select).value == "vector"
        assert s.query_one("#ask-where", Input).value == "visibility == general"
        assert s.query_one("#ask-name", Input).value == "esi"


@pytest.mark.asyncio
async def test_form_defaults_follow_selected_ask(tmp_path, monkeypatch):
    # the form's grounding/mode default to the SELECTED ask's declared values, so a
    # no-retrieval ask (advisor) is not silently driven at 1.0/hybrid.
    async def _none(corpus):
        return []
    monkeypatch.setattr(ask_runner, "list_queries", _none)
    defaults = {"advisor": {"grounding": 0.0, "mode": "none"},
                "audiencias": {"grounding": 0.2, "mode": "hybrid"}}
    screen = AskScreen(tmp_path, ["advisor", "audiencias"], defaults)
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        s = pilot.app.screen
        assert s.query_one("#ask-grounding", Input).value == "0.0"   # advisor's declared
        assert s.query_one("#ask-mode", Select).value == "none"
        s.query_one("#ask-which", Select).value = "audiencias"       # switch the ask
        await pilot.pause()
        assert s.query_one("#ask-grounding", Input).value == "0.2"   # follows the new ask
        assert s.query_one("#ask-mode", Select).value == "hybrid"


@pytest.mark.asyncio
async def test_saved_query_overrides_ask_defaults(tmp_path, monkeypatch):
    # loading a saved query restores ITS grounding/mode; the ask-follows-default sync
    # must not clobber them even though the ask itself changes.
    item = {"name": "q1", "ask": "audiencias", "question": "¿q?",
            "grounding": 1.0, "mode": "vector", "where": None}

    async def _one(corpus):
        return [item]

    monkeypatch.setattr(ask_runner, "list_queries", _one)
    defaults = {"advisor": {"grounding": 0.0, "mode": "none"},
                "audiencias": {"grounding": 0.2, "mode": "hybrid"}}
    screen = AskScreen(tmp_path, ["advisor", "audiencias"], defaults)
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        s = pilot.app.screen
        lst = s.query_one("#ask-saved", OptionList)
        event = OptionList.OptionSelected(lst, lst.get_option_at_index(0), 0)
        await screen.on_option_list_option_selected(event)
        await pilot.pause()
        assert s.query_one("#ask-which", Select).value == "audiencias"
        assert s.query_one("#ask-grounding", Input).value == "1.0"   # saved, not 0.2
        assert s.query_one("#ask-mode", Select).value == "vector"    # saved, not hybrid


@pytest.mark.asyncio
async def test_run_shows_error_on_subprocess_failure(tmp_path, monkeypatch):
    async def _boom(corpus, ask_id, question, *, grounding, mode, where):
        raise RuntimeError("corpus engine: boom")
    async def _none(corpus):
        return []
    monkeypatch.setattr(ask_runner, "run_ask", _boom)
    monkeypatch.setattr(ask_runner, "list_queries", _none)
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        pilot.app.screen.query_one("#ask-question", Input).value = "¿q?"
        await screen.run_query()
        await pilot.pause()
        assert "boom" in str(pilot.app.screen.query_one("#ask-result", Static).content)


@pytest.mark.asyncio
async def test_out_of_range_grounding_shows_friendly_message(tmp_path, monkeypatch):
    async def _none(corpus):
        return []
    monkeypatch.setattr(ask_runner, "list_queries", _none)
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        pilot.app.screen.query_one("#ask-question", Input).value = "¿q?"
        pilot.app.screen.query_one("#ask-grounding", Input).value = "2.0"
        await screen.run_query()
        await pilot.pause()
        assert "grounding" in str(pilot.app.screen.query_one("#ask-result", Static).content)


@pytest.mark.asyncio
async def test_save_result_guarded_when_question_empty(tmp_path, monkeypatch):
    called = {"n": 0}
    async def _save(*a, **k):
        called["n"] += 1
        return "/x.md"
    async def _none(corpus):
        return []
    monkeypatch.setattr(ask_runner, "save_query", _save)
    monkeypatch.setattr(ask_runner, "list_queries", _none)
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        await screen.save(definition_only=True)        # question blank
        await pilot.pause()
        assert called["n"] == 0
        assert "question" in str(pilot.app.screen.query_one("#ask-result", Static).content)


@pytest.mark.asyncio
async def test_save_result_guarded_when_ask_changed_after_run(tmp_path, monkeypatch):
    record = {"ask": "answer", "question": "¿q?", "answer": "x", "passages": []}
    async def _ask(corpus, ask_id, question, *, grounding, mode, where):
        return record
    saved = {"n": 0}
    async def _save(*a, **k):
        saved["n"] += 1
        return "/x.md"
    async def _none(corpus):
        return []
    monkeypatch.setattr(ask_runner, "run_ask", _ask)
    monkeypatch.setattr(ask_runner, "save_query", _save)
    monkeypatch.setattr(ask_runner, "list_queries", _none)
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        s = pilot.app.screen
        s.query_one("#ask-question", Input).value = "¿q?"
        await screen.run_query()                            # record.ask == "answer"
        s.query_one("#ask-which", Select).value = "find"    # now mismatched
        await screen.save(definition_only=False)
        await pilot.pause()
        assert saved["n"] == 0
        assert "run the query" in str(s.query_one("#ask-result", Static).content)


@pytest.mark.asyncio
async def test_save_row_hidden_until_a_successful_run(tmp_path, monkeypatch):
    record = {"ask": "answer", "question": "¿q?", "answer": "Sí. [aaaaaaaaaaaa:r1]",
              "passages": [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "x",
                            "score": 0.4, "retriever": "hybrid", "span": [0, 1],
                            "name": "doc.md"}]}

    async def _ask(corpus, ask_id, question, *, grounding, mode, where):
        return record

    async def _none(corpus):
        return []

    monkeypatch.setattr(ask_runner, "run_ask", _ask)
    monkeypatch.setattr(ask_runner, "list_queries", _none)
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        s = pilot.app.screen
        assert s.query_one("#ask-save-row").has_class("hidden")          # hidden at start
        s.query_one("#ask-question", Input).value = "¿q?"
        await screen.run_query()
        await pilot.pause()
        assert not s.query_one("#ask-save-row").has_class("hidden")      # revealed after a run


@pytest.mark.asyncio
async def test_details_toggle_shows_provenance(tmp_path, monkeypatch):
    record = {"ask": "answer", "question": "¿q?", "answer": "Sí. [aaaaaaaaaaaa:r1]",
              "passages": [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "x", "score": 0.4,
                            "retriever": "hybrid", "span": [0, 1], "name": "doc.md"}],
              "provenance": {"model": "claude-opus-4-8",
                             "usage": {"input_tokens": 1234, "output_tokens": 480,
                                       "cache_read_input_tokens": 21434},
                             "cost_usd": 0.046, "retrieval_ms": 312, "synthesis_ms": 4103,
                             "total_ms": 4421, "prompt": "GROUNDING\n\nPregunta: ¿q?"}}

    async def _ask(corpus, ask_id, question, *, grounding, mode, where):
        return record

    async def _none(corpus):
        return []

    monkeypatch.setattr(ask_runner, "run_ask", _ask)
    monkeypatch.setattr(ask_runner, "list_queries", _none)
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test() as pilot:
        await pilot.pause()
        s = pilot.app.screen
        s.query_one("#ask-question", Input).value = "¿q?"
        await screen.run_query()
        await pilot.pause()
        assert s.query_one("#ask-details-panel").has_class("hidden")     # hidden until toggled
        screen._toggle_details()
        await pilot.pause()
        assert not s.query_one("#ask-details-panel").has_class("hidden")
        txt = str(s.query_one("#ask-details-text", Static).content)
        assert "claude-opus-4-8" in txt and "1234 in / 480 out" in txt
        assert "Pregunta: ¿q?" in txt                                    # the prompt is shown


@pytest.mark.asyncio
async def test_pagedown_scrolls_answer_even_when_focus_is_on_the_form(tmp_path, monkeypatch):
    from shapes.corpus.renderer.tui.ask_screen import _Pane
    ans = "\n".join(f"linea {i} [aaaaaaaaaaaa:r1]" for i in range(80))
    record = {"ask": "answer", "question": "q", "answer": ans,
              "passages": [{"doc_id": "aaaaaaaaaaaa", "ref": "r1", "text": "x", "score": 0.4,
                            "retriever": "hybrid", "span": [0, 1], "name": "d.pdf"}]}

    async def _ask(*a, **k):
        return record

    async def _none(c):
        return []

    monkeypatch.setattr(ask_runner, "run_ask", _ask)
    monkeypatch.setattr(ask_runner, "list_queries", _none)
    screen = AskScreen(tmp_path, ["find", "answer"])
    async with _Host(screen).run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        s = pilot.app.screen
        s.query_one("#ask-question", Input).value = "q"
        await screen.run_query()
        await pilot.pause()
        rb = s.query_one("#ask-result-scroll", _Pane)
        s.query_one("#ask-question", Input).focus()      # focus drifts off the answer pane
        await pilot.pause()
        await pilot.press("pagedown")
        await pilot.pause()
        assert rb.scroll_y > 0                            # screen-level binding still scrolled it
