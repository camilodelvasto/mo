# tests/test_corpus_tui_labels.py
import pathlib, tempfile
from shapes.corpus.renderer.tui import labels


def test_label_defaults_to_the_key_when_no_file():
    with tempfile.TemporaryDirectory() as tmp:
        m = labels.load(pathlib.Path(tmp))
        assert labels.label(m, "tipo_documento") == "tipo_documento"
        assert labels.label(m, "pending") == "pending"


def test_label_uses_language_file_when_present():
    with tempfile.TemporaryDirectory() as tmp:
        (pathlib.Path(tmp) / "language.yaml").write_text(
            "labels:\n  tipo_documento: Type\n  pending: Needs work\n")
        m = labels.load(pathlib.Path(tmp))
        assert labels.label(m, "tipo_documento") == "Type"
        assert labels.label(m, "pending") == "Needs work"
        assert labels.label(m, "audiencia") == "audiencia"   # unmapped → key verbatim
