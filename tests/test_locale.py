import pytest

from shapes.sheets.src.locale import Locale, resolve_locale, resolve_export_locale


def test_resolve_known_locale():
    loc = resolve_locale("de_DE")
    assert loc.name == "de_DE"
    assert loc.decimal_separator == ","
    assert loc.thousands_separator == "."
    assert loc.csv_delimiter == ";"
    assert loc.xlsx_number_format == '#.##0,00'


def test_resolve_en_us():
    loc = resolve_locale("en_US")
    assert loc.decimal_separator == "."
    assert loc.csv_delimiter == ","
    assert loc.date_format == "%Y-%m-%d"


def test_resolve_es_co():
    loc = resolve_locale("es_CO")
    assert loc.decimal_separator == ","
    assert loc.csv_delimiter == ";"
    assert loc.date_format == "%d/%m/%Y"


def test_resolve_unknown_locale_raises():
    with pytest.raises(ValueError, match="Unknown locale"):
        resolve_locale("xx_XX")


def test_resolve_export_locale_uses_corpus_default():
    loc = resolve_export_locale("de_DE", {})
    assert loc.name == "de_DE"


def test_resolve_export_locale_export_overrides_corpus():
    loc = resolve_export_locale("de_DE", {"locale": "en_US"})
    assert loc.name == "en_US"
    assert loc.csv_delimiter == ","


def test_resolve_export_locale_csv_override():
    loc = resolve_export_locale("de_DE", {"csv": {"delimiter": "\t"}})
    assert loc.csv_delimiter == "\t"
    assert loc.decimal_separator == ","


def test_resolve_export_locale_encoding_override():
    loc = resolve_export_locale("de_DE", {"csv": {"encoding": "utf-8"}})
    assert loc.encoding == "utf-8"


def test_all_locales_have_utf8sig_by_default():
    for name in ("de_DE", "en_US", "es_CO"):
        loc = resolve_locale(name)
        assert loc.encoding == "utf-8-sig"
