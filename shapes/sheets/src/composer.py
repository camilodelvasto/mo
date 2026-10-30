"""LLM editorial pass for sheet import. Builds prompts, parses responses."""

import json
import re
from pathlib import Path


REQUIRED_OUTPUT_KEYS = {"title", "header_map", "fields", "pipeline", "keys", "view"}


def build_composer_prompt(
    analysis: dict,
    sheet_name: str,
    corpus_name: str,
    schema_text: str,
    field_options_text: str,
    pipeline_reference_text: str,
    template_list: list[str],
) -> str:
    """Build the full prompt for the LLM editorial pass."""
    analysis_json = json.dumps(analysis, indent=2)
    templates_block = "\n".join(f"- {t}" for t in template_list)

    return f"""You are an editorial assistant for a structured data system called moui sheets.

A user is importing a file into a sheet named "{sheet_name}" in the corpus "{corpus_name}".

Below is the deterministic analysis of the file's columns. Use it to make editorial decisions about how to structure this sheet.

## Analysis

```json
{analysis_json}
```

## Sheet Schema

The output must conform to this JSON schema:

```json
{schema_text}
```

## Field Options Reference

Each field in the "fields" object can be a shorthand string (e.g. "string", "integer") or an object with these properties:

{field_options_text}

## Pipeline Reference

The "pipeline.inputs" object defines how data enters the sheet:

{pipeline_reference_text}

## Available Prompt Templates

These are the prompt templates available in this sheet. Pick from this list for pipeline inputs that use inference. Do not invent new template names.

{templates_block}

## Rules

1. Every column header from the analysis MUST appear in header_map, mapped to a field name (snake_case).
2. If the analysis detected enum values, use them exactly.
3. Types must be compatible with what the analysis inferred. Do not contradict the analysis unless you have a strong editorial reason.
4. Keys in the fields object must be unique snake_case identifiers.
5. Include a primary key field (type "primary") as the first field, even if the source data has no obvious ID column.
6. The "view" object can contain display preferences.
7. The "keys" object can contain keyboard shortcut bindings.

## Your Task

Return a single JSON object with these keys: title, header_map, fields, pipeline, keys, view.

- title: A human-readable title for the sheet.
- header_map: Maps each CSV/XLSX column header to the field name it should populate.
- fields: The full field definitions for sheet.yaml.
- pipeline: The pipeline configuration with inputs.
- keys: Keyboard shortcut bindings (can be empty object).
- view: Display configuration (can be empty object).

Return ONLY the JSON object. No explanation, no markdown fencing."""


def parse_composer_response(raw: str) -> dict:
    """Parse JSON from raw LLM output. Handles both raw JSON and markdown-fenced JSON."""
    text = raw.strip()

    # Try extracting from markdown fence first
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    data = json.loads(text)

    missing = REQUIRED_OUTPUT_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required keys: {', '.join(sorted(missing))}")

    return data


def run_composer(
    analysis: dict,
    sheet_name: str,
    corpus_name: str,
    templates_dir: Path,
    schema_path: Path,
    backend_name: str,
    backend_model: str,
) -> dict:
    """Run the full LLM editorial pass: build prompt, call backend, parse response."""
    from shapes.sheets.src.inference import load_backend

    schema_text = schema_path.read_text()

    # List available prompt templates
    template_list = []
    if templates_dir.exists():
        for p in sorted(templates_dir.iterdir()):
            if p.suffix == ".md":
                first_line = p.read_text().split("\n", 1)[0].strip().lstrip("# ")
                template_list.append(f"{p.name} — {first_line}")

    field_options_text = (
        "- type (required): string, integer, number, boolean, date, datetime, enum, primary, url\n"
        "- label: Display label (auto-generated from field name if omitted)\n"
        "- values: Array of allowed values (required for enum type)\n"
        "- width: Column width in characters\n"
        "- align: left, right, or center\n"
        "- description: Human-readable description of the field\n"
        "- action: Action to perform (e.g. 'open' for URL fields)\n"
        "- key: Single-character keyboard shortcut"
    )

    pipeline_reference_text = (
        "Each input has:\n"
        "- op (required): insert, update, or append\n"
        "- prompt: Name of the prompt template file (from the list above)\n"
        "- description: Human-readable description\n"
        "- key: Single-character keyboard shortcut\n"
        "- bypass_inference: true to skip LLM (for direct data entry)\n"
        "- preprocess: Preprocessor name\n"
        "- browser: none, headless, or visible\n"
        "- target_field: Field to target for append operations\n"
        "- context: Object mapping field names to 'required'"
    )

    prompt = build_composer_prompt(
        analysis=analysis,
        sheet_name=sheet_name,
        corpus_name=corpus_name,
        schema_text=schema_text,
        field_options_text=field_options_text,
        pipeline_reference_text=pipeline_reference_text,
        template_list=template_list,
    )

    # Build JSON schema for structured output
    output_schema = {
        "type": "object",
        "required": list(REQUIRED_OUTPUT_KEYS),
        "properties": {
            "title": {"type": "string"},
            "header_map": {"type": "object"},
            "fields": {"type": "object"},
            "pipeline": {"type": "object"},
            "keys": {"type": "object"},
            "view": {"type": "object"},
        },
    }

    backend = load_backend(backend_name)
    result = backend.complete(prompt, output_schema, backend_model)

    if result.error:
        raise RuntimeError(f"Backend error: {result.error}")

    if result.data:
        return result.data

    return parse_composer_response(result.raw_response)
