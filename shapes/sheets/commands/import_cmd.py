# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapter: mo sheets import <file> --corpus <corpus> --name <name> [--sheet <xlsx_sheet>] [--backend <name>]"""
import argparse
import json
import sys
from pathlib import Path


def _resolve_import_backend(corpus_root, override):
    if override:
        if ":" in override:
            return override.split(":", 1)
        return override, "default"
    moui_path = corpus_root / "moui.json"
    if moui_path.exists():
        manifest = json.loads(moui_path.read_text())
        import_backend = manifest.get("import", {}).get("backend")
        if import_backend:
            if isinstance(import_backend, str):
                return import_backend, "default"
            return import_backend["backend"], import_backend.get("model", "default")
    return "claude", "default"


def run(corpus_root: Path, instance: str, args: list) -> None:
    parser = argparse.ArgumentParser(prog="mo sheets import")
    parser.add_argument("file", type=str)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--sheet", default=None, help="XLSX sheet name")
    parser.add_argument("--backend", default=None)
    parsed = parser.parse_args(args)

    from shapes.sheets.src.analyzer import analyze_file, _read_csv, _read_xlsx
    from shapes.sheets.src.composer import run_composer
    from shapes.sheets.src.validator import validate_composer_output, ValidationError
    from shapes.sheets.src.writer import write_import
    from shapes.sheets.src.rebuild import rebuild_state
    from cli.output import header, detail, success, done

    corpus_root = Path(corpus_root)
    file_path = Path(parsed.file)
    corpus_name = parsed.corpus
    sheet_name = parsed.name
    xlsx_sheet = parsed.sheet

    shape_root = Path(__file__).parent.parent
    templates_dir = shape_root / "templates" / "prompts"
    schema_path = shape_root / "schemas" / "sheet.v1.json"
    target_dir = corpus_root / "content" / corpus_name / sheet_name

    backend_name, backend_model = _resolve_import_backend(corpus_root, parsed.backend)

    # Check target doesn't already exist
    if target_dir.exists() and any(target_dir.iterdir()):
        print(f"Error: target directory already exists: {target_dir}", file=sys.stderr)
        sys.exit(1)

    header("Importing:", file_path.name)
    detail("Target:", f"content/{corpus_name}/{sheet_name}/")
    detail("Backend:", f"{backend_name}:{backend_model}")

    # Phase 1: analyze
    detail("Phase:", "analyzing file...")
    analysis = analyze_file(file_path, sheet_name=xlsx_sheet)
    detail("Rows:", str(analysis["row_count"]))
    detail("Columns:", str(len(analysis["columns"])))

    # Phase 2: compose schema via LLM
    detail("Phase:", "composing schema (LLM)...")
    composer_output = run_composer(
        analysis, sheet_name, corpus_name,
        templates_dir, schema_path,
        backend_name, backend_model,
    )

    # Phase 3: validate
    detail("Phase:", "validating...")
    try:
        validate_composer_output(composer_output, analysis, templates_dir)
    except ValidationError as e:
        print(f"\nValidation failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Phase 4: re-read source data for writer
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        headers, data_rows = _read_csv(file_path)
    elif suffix in (".xlsx", ".xls"):
        headers, data_rows = _read_xlsx(file_path, xlsx_sheet)
    else:
        print(f"Error: unsupported file type: {suffix}", file=sys.stderr)
        sys.exit(1)

    # Phase 5: write files
    detail("Phase:", "writing files...")
    report = write_import(target_dir, composer_output, analysis, headers, data_rows, templates_dir)

    # Stamp instance into sheet.yaml
    import yaml
    sheet_path = target_dir / "sheet.yaml"
    sheet_data = yaml.safe_load(sheet_path.read_text())
    sheet_data["instance"] = instance
    sheet_path.write_text(yaml.dump(sheet_data, default_flow_style=False, sort_keys=False))

    # Phase 6: rebuild state.sqlite
    detail("Phase:", "rebuilding state.sqlite...")
    rebuild_state(target_dir)

    # Summary
    print()
    fields_count = len(composer_output.get("fields", {}))
    col_count = len(analysis["columns"])
    success(f"Imported {analysis['row_count']} rows from {file_path.name} into content/{corpus_name}/{sheet_name}/")
    detail("Columns:", f"{col_count} -> fields: {fields_count}")

    # Enums
    for col in analysis["columns"]:
        if col.get("enum_values"):
            detail("Enums:", f"{col['header']}: {len(col['enum_values'])} values")

    # Pipeline
    pipeline_inputs = composer_output.get("pipeline", {}).get("inputs", {})
    if pipeline_inputs:
        detail("Pipeline:", ", ".join(pipeline_inputs.keys()))

    # Prompts
    prompts = []
    for inp_name, inp_config in pipeline_inputs.items():
        tpl = inp_config.get("prompt_template")
        if tpl:
            prompts.append(f"{tpl}.md")
    if prompts:
        detail("Prompts:", ", ".join(prompts))

    detail("Backend:", f"{backend_name}:{backend_model}")
    detail("Rebuild:", "ok")

    print()
    print(f"Open with: mo sheets serve {sheet_name}")
    done()
