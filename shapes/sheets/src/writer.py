"""Deterministic file writer for sheet import. No LLM."""
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml


def write_import(
    target_dir: Path,
    composer_output: dict,
    analysis: dict,
    headers: list[str],
    data_rows: list[list[str]],
    templates_dir: Path,
) -> dict:
    """Write all import artifacts to target_dir. Returns an import report dict.

    Raises FileExistsError if target_dir already exists and is non-empty.
    """
    target_dir = Path(target_dir)
    if target_dir.exists() and any(target_dir.iterdir()):
        raise FileExistsError(f"Target directory already exists: {target_dir}")

    header_map = composer_output["header_map"]
    fields = composer_output["fields"]

    # Build header-to-position index
    header_positions = {h: i for i, h in enumerate(headers)}

    # Create directory structure
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "prompts").mkdir(exist_ok=True)
    (target_dir / "ingest" / "inbox").mkdir(parents=True)
    (target_dir / "ingest" / "staging").mkdir(exist_ok=True)
    (target_dir / "ingest" / "failed").mkdir(exist_ok=True)

    # 1. Write sheet.yaml
    sheet_data = _build_sheet_yaml(composer_output)
    (target_dir / "sheet.yaml").write_text(
        yaml.dump(sheet_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    )

    # 2. Write exports.yaml
    (target_dir / "exports.yaml").write_text(
        yaml.dump(
            {"exports": {"local": {"formats": ["csv", "xlsx"]}}},
            default_flow_style=False,
        )
    )

    # 3. Copy prompt templates
    templates_copied = []
    for input_name, cfg in composer_output.get("pipeline", {}).get("inputs", {}).items():
        if not isinstance(cfg, dict):
            continue
        template_name = cfg.get("prompt_template")
        if not template_name:
            continue
        src = templates_dir / f"{template_name}.md"
        dst = target_dir / "prompts" / f"{template_name}.md"
        shutil.copy2(src, dst)
        templates_copied.append(f"{template_name}.md")

    # Build coercion map from analysis: source_header -> date_format (if non-ISO)
    coercion_map = {}
    for col in analysis.get("columns", []):
        fmt = col.get("date_format")
        if fmt and fmt != "%Y-%m-%d" and fmt not in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
            coercion_map[col["header"]] = fmt

    # 4. Generate ops.jsonl
    import_ts = datetime.now(timezone.utc)
    ops_lines = []

    for row_idx, row in enumerate(data_rows):
        row_id = _generate_row_id(import_ts, row_idx)
        values = {}

        for source_header, field_name in header_map.items():
            if field_name is None:
                continue
            col_idx = header_positions.get(source_header)
            if col_idx is None or col_idx >= len(row):
                continue
            raw_value = row[col_idx]
            if raw_value.strip():
                coerced = _coerce_value(raw_value.strip(), source_header, coercion_map)
                values[field_name] = coerced

        # Add created_at/updated_at if declared in fields
        ts_str = import_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        if "created_at" in fields:
            values["created_at"] = ts_str
        if "updated_at" in fields:
            values["updated_at"] = ts_str

        op = {
            "op": "insert",
            "ts": ts_str,
            "id": row_id,
            "values": values,
        }
        ops_lines.append(json.dumps(op, ensure_ascii=False))

    (target_dir / "ops.jsonl").write_text("\n".join(ops_lines) + "\n" if ops_lines else "")

    # 5. Create empty journal
    (target_dir / "ingest" / "journal.jsonl").write_text("")

    # Build report
    enum_fields = [
        (name, len(spec.get("values", [])))
        for name, spec in fields.items()
        if isinstance(spec, dict) and spec.get("type") == "enum"
    ]

    return {
        "row_count": len(data_rows),
        "column_count": sum(1 for v in header_map.values() if v is not None),
        "field_count": len(fields),
        "enum_fields": enum_fields,
        "templates_copied": templates_copied,
        "pipeline_inputs": list(
            composer_output.get("pipeline", {}).get("inputs", {}).keys()
        ),
    }


def _build_sheet_yaml(composer_output: dict) -> dict:
    """Build the sheet.yaml dict from composer output."""
    pipeline = _rewrite_pipeline(composer_output.get("pipeline", {}))

    sheet = {
        "instance": "sheets",
        "version": "0.1.0",
        "schema": "sheet.v1.json",
        "title": composer_output.get("title", "Imported Sheet"),
    }

    desc = composer_output.get("description")
    if desc:
        sheet["description"] = desc

    keys = composer_output.get("keys")
    if keys:
        sheet["keys"] = keys

    view = composer_output.get("view")
    if view:
        sheet["view"] = view

    sheet["pipeline"] = pipeline
    sheet["fields"] = composer_output["fields"]

    return sheet


def _rewrite_pipeline(pipeline: dict) -> dict:
    """Convert prompt_template references to prompt file paths."""
    result = {"inputs": {}}
    for name, cfg in pipeline.get("inputs", {}).items():
        entry = dict(cfg)
        template_name = entry.pop("prompt_template", None)
        if template_name:
            entry["prompt"] = f"prompts/{template_name}.md"
        result["inputs"][name] = entry
    return result


def _generate_row_id(base_ts: datetime, offset: int) -> str:
    """Generate a row ID: r + YYYYMMDDHHMMSS, staggered by 1 second per row."""
    ts = base_ts + timedelta(seconds=offset)
    return f"r{ts.strftime('%Y%m%d%H%M%S')}"


def _coerce_value(value: str, source_header: str, coercion_map: dict) -> str:
    """Coerce a value to ISO format if the column has a non-ISO date format."""
    source_fmt = coercion_map.get(source_header)
    if not source_fmt:
        return value
    try:
        dt = datetime.strptime(value, source_fmt)
        if "H" in source_fmt or "M" in source_fmt:
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return value  # fall back to raw string
