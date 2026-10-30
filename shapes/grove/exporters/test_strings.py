"""Tests for grove system strings loader."""
import pytest
from pathlib import Path
import yaml

from strings import load_strings, MissingStringsError


@pytest.fixture
def languages_dir(tmp_path):
    """Engine catalog with reference keys."""
    lang_dir = tmp_path / "languages"
    lang_dir.mkdir()
    ref = {
        "search_placeholder": "Search posts...",
        "search_no_results": "No results found.",
        "toc": "Table of Contents",
        "toggle_theme": "Toggle theme",
        "clear_site": "Clear site data",
    }
    (lang_dir / "en.yaml").write_text(yaml.dump(ref))
    return lang_dir


@pytest.fixture
def themes_dir(tmp_path):
    """Theme dir with default and dark variants."""
    default = tmp_path / "themes" / "default"
    default.mkdir(parents=True)
    dark = tmp_path / "themes" / "dark"
    dark.mkdir(parents=True)
    return tmp_path / "themes"


class TestLoadStrings:
    def test_loads_from_default_theme(self, themes_dir, languages_dir):
        strings = {
            "search_placeholder": "Buscar...",
            "search_no_results": "Sin resultados.",
            "toc": "Índice",
            "toggle_theme": "Cambiar tema",
            "clear_site": "Borrar datos",
        }
        (themes_dir / "default" / "strings.yaml").write_text(yaml.dump(strings))
        result = load_strings(themes_dir, languages_dir)
        assert result["search_placeholder"] == "Buscar..."

    def test_dark_overrides_default(self, themes_dir, languages_dir):
        default_strings = {
            "search_placeholder": "Search...",
            "search_no_results": "No results.",
            "toc": "TOC",
            "toggle_theme": "Toggle",
            "clear_site": "Clear",
        }
        (themes_dir / "default" / "strings.yaml").write_text(yaml.dump(default_strings))
        dark_strings = {"search_placeholder": "Dark search..."}
        (themes_dir / "dark" / "strings.yaml").write_text(yaml.dump(dark_strings))
        result = load_strings(themes_dir, languages_dir)
        assert result["search_placeholder"] == "Dark search..."
        assert result["toc"] == "TOC"

    def test_missing_strings_file_throws(self, themes_dir, languages_dir):
        with pytest.raises(FileNotFoundError):
            load_strings(themes_dir, languages_dir)

    def test_missing_keys_reports_all_at_once(self, themes_dir, languages_dir):
        partial = {"search_placeholder": "Search...", "toc": "TOC"}
        (themes_dir / "default" / "strings.yaml").write_text(yaml.dump(partial))
        with pytest.raises(MissingStringsError) as exc_info:
            load_strings(themes_dir, languages_dir)
        err = exc_info.value
        assert "search_no_results" in str(err)
        assert "toggle_theme" in str(err)
        assert "clear_site" in str(err)
        assert str(themes_dir / "default" / "strings.yaml") in str(err)

    def test_extra_required_keys_are_validated(self, themes_dir, languages_dir):
        # a feature (e.g. chat) demands extra keys only for groves that use it —
        # the base set passes, but the extra key is missing → throws naming it.
        base = {"search_placeholder": "S", "search_no_results": "N", "toc": "T",
                "toggle_theme": "TT", "clear_site": "C"}
        (themes_dir / "default" / "strings.yaml").write_text(yaml.dump(base))
        load_strings(themes_dir, languages_dir)                       # base set: fine
        with pytest.raises(MissingStringsError) as exc:
            load_strings(themes_dir, languages_dir, extra_required={"chat_send"})
        assert "chat_send" in str(exc.value)

    def test_extra_required_keys_pass_when_present(self, themes_dir, languages_dir):
        s = {"search_placeholder": "S", "search_no_results": "N", "toc": "T",
             "toggle_theme": "TT", "clear_site": "C", "chat_send": "Enviar"}
        (themes_dir / "default" / "strings.yaml").write_text(yaml.dump(s))
        result = load_strings(themes_dir, languages_dir, extra_required={"chat_send"})
        assert result["chat_send"] == "Enviar"

    def test_dark_override_is_optional(self, themes_dir, languages_dir):
        strings = {
            "search_placeholder": "Search...",
            "search_no_results": "No results.",
            "toc": "TOC",
            "toggle_theme": "Toggle",
            "clear_site": "Clear",
        }
        (themes_dir / "default" / "strings.yaml").write_text(yaml.dump(strings))
        result = load_strings(themes_dir, languages_dir)
        assert result["toc"] == "TOC"
