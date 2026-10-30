# tests/test_corpus_tui_keymap.py
from pathlib import Path

import pytest

from shapes.corpus.renderer.tui import keymap
from shapes.corpus.renderer.tui.keymap import BindingError, load_bindings, footer_text

_DEFAULT = Path("shapes/corpus/renderer/tui/bindings.default.yaml")


def _write_override(tmp_path, text):
    (tmp_path / "bindings.yaml").write_text(text)
    return tmp_path


def test_load_default_only(tmp_path):
    bindings = load_bindings(_DEFAULT, tmp_path, keymap.READ_CAPABILITIES)
    keys = {b.key for b in bindings}
    assert {"1", "2", "f", "o", "a", "e"} == keys
    lens = sorted([b for b in bindings if b.capability == "lens"], key=lambda b: b.key)
    assert [b.args for b in lens] == [{"lens": "all"}, {"lens": "pending"}]


def test_override_merges_per_capability(tmp_path):
    _write_override(tmp_path,
        "bindings:\n  - { capability: filter, key: 'F', label: find }\n")
    bindings = load_bindings(_DEFAULT, tmp_path, keymap.READ_CAPABILITIES)
    filt = [b for b in bindings if b.capability == "filter"]
    assert len(filt) == 1 and filt[0].key == "F" and filt[0].label == "find"
    assert any(b.capability == "open-artifact" and b.key == "o" for b in bindings)


def test_duplicate_key_after_merge_throws(tmp_path):
    _write_override(tmp_path,
        "bindings:\n  - { capability: open-artifact, key: 'f', label: open }\n")
    with pytest.raises(BindingError, match="f"):
        load_bindings(_DEFAULT, tmp_path, keymap.READ_CAPABILITIES)


def test_reserved_spine_key_throws(tmp_path):
    _write_override(tmp_path,
        "bindings:\n  - { capability: filter, key: 'q', label: filter }\n")
    with pytest.raises(BindingError, match="reserved"):
        load_bindings(_DEFAULT, tmp_path, keymap.READ_CAPABILITIES)


def test_unknown_capability_throws(tmp_path):
    _write_override(tmp_path,
        "bindings:\n  - { capability: confirm, key: 'c', label: confirm }\n")
    with pytest.raises(BindingError, match="confirm"):
        load_bindings(_DEFAULT, tmp_path, keymap.READ_CAPABILITIES)


def test_footer_text_is_the_honest_catalogue_keys(tmp_path):
    # The catalogue footer shows only its real keys (lens + open) plus the
    # frame-owned affordances. `filter` is the document screen's capability and
    # is NOT advertised here; the old hard/soft lenses are gone.
    footer = footer_text(load_bindings(_DEFAULT, tmp_path, keymap.READ_CAPABILITIES))
    assert "1 all" in footer and "2 pending" in footer
    assert "/ search" in footer and "tab plane" in footer
    assert "hard" not in footer and "soft" not in footer
    assert "f filter" not in footer


def test_footer_text_derives_from_labels(tmp_path):
    # The footer is the i18n seam: rebinding a lens label is a file edit, not an
    # app change.
    before = footer_text(load_bindings(_DEFAULT, tmp_path, keymap.READ_CAPABILITIES))
    _write_override(tmp_path,
        "bindings:\n  - { capability: lens, key: '2', args: { lens: pending }, label: SEARCHTERM }\n")
    after = footer_text(load_bindings(_DEFAULT, tmp_path, keymap.READ_CAPABILITIES))
    assert "SEARCHTERM" in after and after != before
