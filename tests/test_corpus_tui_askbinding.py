# tests/test_corpus_tui_askbinding.py
from pathlib import Path

from shapes.corpus.renderer.tui import keymap

TUI = Path(keymap.__file__).parent


def test_ask_capability_registered():
    assert "ask" in keymap.READ_CAPABILITIES


def test_default_bindings_include_ask_on_a():
    bindings = keymap.load_bindings(
        TUI / "bindings.default.yaml", Path("."), keymap.READ_CAPABILITIES)
    ask = [b for b in bindings if b.capability == "ask"]
    assert len(ask) == 1
    assert ask[0].key == "a"
