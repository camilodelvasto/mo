# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapter: mo sheets export <sheet> [name] [-n]"""
import json as _json
import sys
from pathlib import Path

import yaml as _yaml


def run(corpus_root: Path, instance: str, args: list) -> None:
    if not args:
        print("Usage: mo sheets export <sheet> [name] [-n]")
        sys.exit(1)

    from shapes.sheets.src.cli_utils import resolve_sheet
    from shapes.sheets.src.exports import (
        load_exports, validate_exports, resolve_output_path, ExportsError,
    )
    from shapes.sheets.src.fields import parse_fields
    from shapes.sheets.src.locale import resolve_export_locale

    sheet_name = args[0]
    dry_run = "-n" in args
    remaining = [a for a in args[1:] if a != "-n"]
    export_name = remaining[0] if remaining else None

    sheet_dir = resolve_sheet(sheet_name, corpus_root)
    sheet_name_resolved = sheet_dir.name

    try:
        exports = load_exports(sheet_dir)
    except ExportsError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    sheet = _yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    fields = parse_fields(sheet)
    field_names = [f.name for f in fields]

    try:
        validate_exports(exports, field_names)
    except ExportsError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    manifest = _json.loads((corpus_root / "moui.json").read_text())
    corpus_locale = manifest.get("locale", "en_US")

    # List mode
    if export_name is None:
        print(f"Available exports for {sheet_name_resolved}:")
        for name, config in exports.items():
            fmt_str = ", ".join(config["formats"])
            parts = [fmt_str]
            if "fields" in config:
                parts.append(f"{len(config['fields'])} fields")
            export_locale = config.get("locale")
            if export_locale and export_locale != corpus_locale:
                parts.append(export_locale)
            summary = " (".join([parts[0]] + parts[1:]) + (")" if len(parts) > 1 else "")
            line = f"  {name:<12} {summary}"
            if "output" in config:
                line += f" -> {config['output']}"
            print(line)
        return

    if export_name not in exports:
        print(
            f"Error: unknown export '{export_name}'. "
            f"Run 'mo sheets export {sheet_name}' to list.",
            file=sys.stderr,
        )
        sys.exit(1)

    export_config = exports[export_name]

    if "fields" in export_config:
        selected = [f for f in fields if f.name in export_config["fields"]]
        selected.sort(key=lambda f: export_config["fields"].index(f.name))
    else:
        selected = fields

    locale = resolve_export_locale(corpus_locale, export_config)

    import sqlite3
    db_path = sheet_dir / "state.sqlite"
    row_count = 0
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        row_count = conn.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
        conn.close()

    from cli.output import header, detail, output_file, output_dir as output_dir_line, done

    header("Exporting:", sheet_name_resolved)
    detail("Config:", export_name)
    detail("Formats:", ", ".join(export_config["formats"]))
    detail("Locale:", locale.name)
    detail("Rows:", str(row_count))
    detail("Columns:", str(len(selected)))
    if "fields" in export_config:
        detail("Fields:", ", ".join(export_config["fields"]))

    if dry_run:
        detail("Mode:", "dry-run (no files written)")
        for fmt in export_config["formats"]:
            out_path = resolve_output_path(
                export_name, export_config, sheet_dir, sheet_name_resolved, fmt,
            )
            output_file(str(out_path))
        done()
        return

    written = []
    for fmt in export_config["formats"]:
        out_path = resolve_output_path(
            export_name, export_config, sheet_dir, sheet_name_resolved, fmt,
        )
        out_dir = out_path.parent

        if fmt == "csv":
            from shapes.sheets.renderer.csv.export import export as csv_export
            paths = csv_export(sheet_dir, selected, export_config, out_dir, locale)
        elif fmt == "xlsx":
            try:
                from shapes.sheets.renderer.xlsx.export import export as xlsx_export
            except ImportError:
                print("Error: XLSX export requires openpyxl. Install with:", file=sys.stderr)
                print("    pip install openpyxl", file=sys.stderr)
                sys.exit(1)
            paths = xlsx_export(sheet_dir, selected, export_config, out_dir, locale)

        written.extend(paths)

    for p in written:
        output_file(str(p))
    if written:
        output_dir_line(str(written[0].parent))
    done()
