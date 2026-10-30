# shapes/sheets/src/locale.py
"""Locale profiles for export formatting.

Manually curated list. Three locales for v1 — adding one is a single dict entry.
If the list grows past ~10, evaluate babel as a backend.

Encoding lives here for resolution convenience — in practice all locales
use utf-8-sig. The per-format csv: { encoding: "utf-8" } override handles
the exception case (scripting output that doesn't want BOM).
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Locale:
    name: str
    decimal_separator: str
    thousands_separator: str
    date_format: str
    datetime_format: str
    csv_delimiter: str
    xlsx_number_format: str
    xlsx_date_format: str
    encoding: str


LOCALES = {
    "de_DE": Locale(
        name="de_DE",
        decimal_separator=",",
        thousands_separator=".",
        date_format="%d.%m.%Y",
        datetime_format="%d.%m.%Y %H:%M",
        csv_delimiter=";",
        xlsx_number_format='#.##0,00',
        xlsx_date_format="DD.MM.YYYY",
        encoding="utf-8-sig",
    ),
    "en_US": Locale(
        name="en_US",
        decimal_separator=".",
        thousands_separator=",",
        date_format="%Y-%m-%d",
        datetime_format="%Y-%m-%dT%H:%M",
        csv_delimiter=",",
        xlsx_number_format='#,##0.00',
        xlsx_date_format="YYYY-MM-DD",
        encoding="utf-8-sig",
    ),
    "es_CO": Locale(
        name="es_CO",
        decimal_separator=",",
        thousands_separator=".",
        date_format="%d/%m/%Y",
        datetime_format="%d/%m/%Y %H:%M",
        csv_delimiter=";",
        xlsx_number_format='#.##0,00',
        xlsx_date_format="DD/MM/YYYY",
        encoding="utf-8-sig",
    ),
}

SUPPORTED_LOCALES = list(LOCALES.keys())


def resolve_locale(name: str) -> Locale:
    if name not in LOCALES:
        raise ValueError(
            f"Unknown locale: {name}. Supported: {SUPPORTED_LOCALES}"
        )
    return LOCALES[name]


def resolve_export_locale(corpus_locale: str, export_config: dict) -> Locale:
    base = resolve_locale(export_config.get("locale", corpus_locale))
    if "csv" in export_config:
        csv_overrides = export_config["csv"]
        base = replace(
            base,
            csv_delimiter=csv_overrides.get("delimiter", base.csv_delimiter),
            encoding=csv_overrides.get("encoding", base.encoding),
        )
    return base
