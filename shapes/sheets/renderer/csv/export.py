"""CSV export renderer.

Receives pre-filtered, pre-ordered Field objects and a resolved Locale.
Reads state.sqlite, writes a CSV file with labels as headers.
"""
import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from shapes.sheets.src.fields import Field
from shapes.sheets.src.locale import Locale


def export(
    content_dir: Path,
    fields: list[Field],
    export_config: dict,
    output_dir: Path,
    locale: Locale,
) -> list[Path]:
    db_path = content_dir / "state.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM rows").fetchall()
    conn.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{content_dir.name}.csv"

    with open(out_path, "w", encoding=locale.encoding, newline="") as f:
        writer = csv.writer(f, delimiter=locale.csv_delimiter)
        writer.writerow([field.label for field in fields])
        for row in rows:
            writer.writerow([
                _format_value(row[field.name], field, locale)
                for field in fields
            ])

    return [out_path]


def _format_value(value, field: Field, locale: Locale) -> str:
    if value is None:
        return ""
    if field.type in ("number", "integer"):
        return _format_number(value, field.type, locale)
    if field.type == "datetime":
        return _format_datetime(value, locale.datetime_format)
    if field.type == "date":
        return _format_datetime(value, locale.date_format)
    return str(value)


def _format_number(value, field_type: str, locale: Locale) -> str:
    try:
        num = float(value)
    except (ValueError, TypeError):
        return str(value)

    if field_type == "integer":
        formatted = f"{int(num):,}".replace(",", "\x00")
        formatted = formatted.replace("\x00", locale.thousands_separator)
        return formatted

    # Format with 2 decimal places, then swap separators
    formatted = f"{num:,.2f}"
    if locale.decimal_separator == ",":
        # Swap: comma->placeholder, dot->comma, placeholder->dot
        formatted = formatted.replace(",", "\x00")
        formatted = formatted.replace(".", ",")
        formatted = formatted.replace("\x00", ".")
    return formatted


def _format_datetime(value, fmt: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime(fmt)
    except (ValueError, TypeError):
        return str(value)
