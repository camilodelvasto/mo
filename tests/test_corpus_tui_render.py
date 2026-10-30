# tests/test_corpus_tui_render.py
from rich.text import Text

from shapes.corpus.renderer.tui import render

DECLARED = ["doc_type", "consent", "tags"]


def _plain(markup: str) -> str:
    return Text.from_markup(markup).plain


def test_columns_are_doc_id_status_then_declared():
    assert render.table_columns(DECLARED) == ["doc_id", "status", "doc_type",
                                              "consent", "tags"]


def test_columns_dedupe_fields_declared_in_multiple_branches():
    # a real flow declares e.g. `summary` in several branch stages; one column.
    assert render.table_columns(["summary", "doc_type", "summary"]) == [
        "doc_id", "status", "summary", "doc_type"]


def test_complete_row_shows_values():
    row = {"doc_id": "3f9a21abcdef", "status": "complete",
           "cells": {"doc_type": {"value": "interview", "by": "model"},
                     "consent": {"value": "given", "by": "operator"},
                     "tags": {"value": ["housing", "tenancy"], "by": "operator"}}}
    cells = render.render_row(row, render.table_columns(DECLARED))
    assert cells[0] == "3f9a21abcdef"
    assert _plain(cells[1]) == "complete"
    assert _plain(cells[2]) == "interview"
    assert "housing" in _plain(cells[4])


def test_proposal_renders_tilde_and_confidence_without_colour():
    row = {"doc_id": "8c01d2aaaaaa", "status": "parked@datasheet",
           "cells": {}, "proposals": {"tags": {"add": ["berlin"], "confidence": 0.71}}}
    cells = render.render_row(row, render.table_columns(DECLARED))
    tags = _plain(cells[4])
    assert "~" in tags and "berlin" in tags and "0.71" in tags


def test_pending_renders_ring_glyph_without_colour():
    row = {"doc_id": "8c01d2aaaaaa", "status": "parked@datasheet",
           "cells": {"consent": {"value": "given", "by": "operator"}},
           "pending": ["consent"]}
    cells = render.render_row(row, render.table_columns(DECLARED))
    assert "◌" in _plain(cells[3])


def test_status_carries_its_accent_markup():
    row = {"doc_id": "a0fcceffffff", "status": "failed@normalize", "cells": {}}
    cells = render.render_row(row, render.table_columns(DECLARED))
    assert "#d4655a" in cells[1]
    assert _plain(cells[1]) == "failed@normalize"


def test_column_widths_proportional_fill_and_sum_to_available():
    cols = ["doc_id", "status", "tipo_documento", "audiencia", "tema"]
    widths = render.column_widths(cols, available=100)
    assert list(widths.keys()) == cols
    assert sum(widths.values()) == 100            # fills the row exactly
    assert widths["tema"] == max(widths.values())  # free-text column largest
    assert all(w >= render.MIN_COL for w in widths.values())  # never collapses
