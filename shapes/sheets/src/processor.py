import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from shapes.sheets.src.fields import Field, parse_fields
from shapes.sheets.src.inference import load_backend, resolve_backend
from shapes.sheets.src.types import InferenceResult

MENTION_RE = re.compile(r'(?:^|\s)@([a-zA-Z0-9_-]+)')


def _build_log_entry(body: str) -> dict:
    match = MENTION_RE.search(body)
    return {
        "ts": _now_iso(),
        "by": match.group(1) if match else "",
        "text": body.strip(),
    }


def process_file(
    file_path: Path,
    content_dir: Path,
    corpus_root: Path | None = None,
    api_url: str = "http://127.0.0.1:4200",
) -> None:
    content_dir = Path(content_dir)
    sheet = yaml.safe_load((content_dir / "sheet.yaml").read_text())
    pipeline = sheet["pipeline"]["inputs"]
    fields = parse_fields(sheet)
    field_map = {f.name: f for f in fields}

    text = file_path.read_text()
    first_line, _, body = text.partition("\n")
    tokens = first_line.split()
    kind = tokens[0]

    handler = pipeline.get(kind)
    if not handler:
        _move_to_failed(file_path, content_dir, f"Unknown input kind: {kind}")
        return

    if handler.get("op") == "append":
        context = _parse_context(tokens)
        row_id = context.get("row_id")
        if not row_id:
            _move_to_failed(file_path, content_dir, f"Missing row_id for {kind}")
            return
        target_field = handler.get("target_field")
        if not target_field:
            _move_to_failed(file_path, content_dir, f"Missing target_field for {kind}")
            return
        entry = _build_log_entry(body)
        op = {
            "op": "append",
            "ts": _now_iso(),
            "id": row_id,
            "field": target_field,
            "entry": entry,
        }
        _post_to_api(op, api_url)
        _write_journal(content_dir, kind, text, InferenceResult(
            data=entry, backend="direct", model="n/a",
            latency_ms=0, error=None, raw_response=body.strip(),
        ), row_id, handler)
        file_path.unlink()
        return

    if handler.get("bypass_inference"):
        _handle_set(file_path, tokens, body, content_dir, field_map, api_url)
        return

    context = _parse_context(tokens)
    handler_context = handler.get("context", {})
    row_id = context.get("row_id")
    row = None
    if handler_context.get("row_id") == "required":
        if not row_id:
            _move_to_failed(file_path, content_dir, f"Missing row_id for {kind}")
            return
        row = _get_row_from_api(row_id, api_url)

    # Preprocess if needed
    source_text = body.strip()
    if handler.get("preprocess") == "trafilatura":
        from shapes.sheets.src.preprocessors.fetch import preprocess
        try:
            browser_mode = handler.get("browser", "headless")
            source_text = preprocess(source_text, browser=browser_mode)
        except Exception as e:
            _move_to_failed(file_path, content_dir, f"Preprocess failed: {e}")
            return

    # Render prompt template
    prompt_path = content_dir / handler["prompt"]
    prompt = _render_prompt(
        prompt_path, body=source_text, row=row, now=_now_iso(), schema=_schema_description(fields)
    )

    # Build JSON schema for inference
    json_schema = _fields_to_json_schema(fields)

    # Call inference
    result = _call_inference(prompt, json_schema, content_dir, corpus_root)

    if result.error or result.data is None:
        _move_to_failed(file_path, content_dir, result.error or "No data returned")
        _write_journal(content_dir, kind, text, result, row_id, handler)
        return

    if _is_empty_data(result.data):
        _move_to_failed(file_path, content_dir, "Inference returned empty values for all fields")
        _write_journal(content_dir, kind, text, result, row_id, handler)
        return

    # Build op
    op_id = row_id or _generate_row_id()
    op = {
        "op": handler["op"],
        "ts": _now_iso(),
        "id": op_id,
        "values": result.data,
    }

    _post_to_api(op, api_url)
    _write_journal(content_dir, kind, text, result, op_id, handler)
    file_path.unlink()


def _handle_set(
    file_path: Path,
    tokens: list[str],
    body: str,
    content_dir: Path,
    field_map: dict[str, Field],
    api_url: str,
) -> None:
    context = _parse_context(tokens)
    row_id = context.get("row_id")
    if not row_id:
        _move_to_failed(file_path, content_dir, "SET requires row_id")
        return

    values = {}
    for line in body.strip().splitlines():
        match = re.match(r"^(\w+)\s*=\s*(.+)$", line.strip())
        if not match:
            continue
        field_name, raw_value = match.group(1), match.group(2).strip()

        if field_name not in field_map:
            _move_to_failed(file_path, content_dir, f"Unknown field: {field_name}")
            return

        field = field_map[field_name]
        try:
            values[field_name] = _coerce_value(raw_value, field)
        except ValueError as e:
            _move_to_failed(file_path, content_dir, str(e))
            return

    if not values:
        _move_to_failed(file_path, content_dir, "No SET directives found")
        return

    op = {"op": "update", "ts": _now_iso(), "id": row_id, "values": values}
    _post_to_api(op, api_url)

    direct_result = InferenceResult(
        data=values, backend="direct", model="n/a",
        latency_ms=0, error=None, raw_response=body.strip(),
    )
    _write_journal(
        content_dir, "SET", f"SET {row_id}\n{body}",
        direct_result, row_id, {"op": "update"},
    )
    file_path.unlink()


def _coerce_value(raw: str, field: Field):
    if field.type == "number":
        return float(raw)
    if field.type == "enum":
        if field.values and raw not in field.values:
            raise ValueError(f"'{raw}' not in enum {field.values}")
        return raw
    return raw


def _render_prompt(template_path: Path, **variables) -> str:
    template = template_path.read_text()
    for key, value in variables.items():
        placeholder = f"{{{{{key}}}}}"
        if placeholder in template and value is None:
            raise ValueError(f"Prompt template requires '{placeholder}' but value is None")
        template = template.replace(placeholder, str(value) if value is not None else "")
    return template


def _schema_description(fields: list[Field]) -> str:
    lines = []
    for field in fields:
        if field.type == "primary":
            continue
        label_part = f" ({field.label})" if field.label != field.name.replace("_", " ").title() else ""
        desc_part = f" — {field.description}" if field.description else ""
        lines.append(f"- {field.name}{label_part}: {field.type}{desc_part}")
    return "\n".join(lines)


def _parse_context(tokens: list[str]) -> dict[str, str]:
    """Parse key=value pairs from first-line tokens after the kind."""
    context = {}
    for token in tokens[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            context[key] = value
    return context


def _fields_to_json_schema(fields: list[Field]) -> dict:
    properties = {}
    for field in fields:
        if field.type == "primary":
            continue
        prop: dict = {}
        if field.description:
            prop["description"] = field.description
        if field.type == "number":
            prop["type"] = "number"
        elif field.type == "enum":
            prop["type"] = "string"
            if field.values:
                prop["enum"] = field.values
        else:
            prop["type"] = "string"
        properties[field.name] = prop
    return {"type": "object", "properties": properties}


def _call_inference(
    prompt: str, json_schema: dict, content_dir: Path, corpus_root: Path | None,
) -> InferenceResult:
    backend_name, model = resolve_backend(
        corpus_root or content_dir.parent.parent, sheet_dir=content_dir
    )
    backend = load_backend(backend_name)
    return backend.complete(prompt, json_schema, model=model)


def _is_empty_data(data: dict) -> bool:
    """True if every value in the data dict is empty/None/zero-length."""
    for v in data.values():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, (list, dict)) and not v:
            continue
        return False
    return True


def _post_to_api(op: dict, api_url: str) -> None:
    import requests
    resp = requests.post(f"{api_url}/api/entries", json=op, timeout=10)
    resp.raise_for_status()


def _get_row_from_api(row_id: str, api_url: str) -> dict:
    import requests
    resp = requests.get(f"{api_url}/api/rows/{row_id}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def _write_journal(
    content_dir: Path, kind: str, input_text: str,
    result: InferenceResult, op_id: str | None, handler: dict,
) -> None:
    prompt_path = handler.get("prompt", "")
    prompt_hash = ""
    if prompt_path:
        full_path = content_dir / prompt_path
        if full_path.exists():
            prompt_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()[:12]

    entry = {
        "ts": _now_iso(),
        "kind": kind,
        "input": input_text[:2000],
        "backend": result.backend,
        "model": result.model,
        "op_id": op_id,
        "op_kind": handler.get("op"),
        "latency_ms": result.latency_ms,
        "prompt_hash": prompt_hash,
    }
    if result.error:
        entry["error"] = result.error

    journal_path = content_dir / "ingest" / "journal.jsonl"
    with open(journal_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _move_to_failed(file_path: Path, content_dir: Path, error: str) -> None:
    failed_dir = content_dir / "ingest" / "failed"
    dest = failed_dir / file_path.name
    shutil.move(str(file_path), str(dest))
    error_path = failed_dir / f"{file_path.name}.error"
    error_path.write_text(error)


def _generate_row_id() -> str:
    now = datetime.now(timezone.utc)
    return f"r{now.strftime('%Y%m%d%H%M%S')}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
