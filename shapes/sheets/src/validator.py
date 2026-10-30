"""Post-LLM validation for sheet import. Every check is a hard fail."""
from pathlib import Path


class ValidationError(Exception):
    pass


COMPATIBLE_TYPES = {
    "string": {"string", "text", "enum"},
    "text": {"text", "string"},
    "integer": {"integer", "number", "string"},
    "number": {"number", "string"},
    "boolean": {"boolean", "string"},
    "date": {"date", "string"},
    "datetime": {"datetime", "string"},
}


def validate_composer_output(output, analysis, templates_dir):
    source_headers = {col["header"] for col in analysis["columns"]}
    header_map = output.get("header_map", {})
    fields = output.get("fields", {})
    pipeline = output.get("pipeline", {})
    keys = output.get("keys", {})

    _check_header_map_keys_exist(header_map, source_headers)
    _check_header_map_covers_all(header_map, source_headers)
    _check_header_map_unique_values(header_map)
    _check_primary_key(fields)
    _check_key_collisions(pipeline, keys, fields)
    _check_enum_integrity(fields, header_map, analysis)
    _check_prompt_templates(pipeline, templates_dir)
    _check_type_compatibility(fields, header_map, analysis)


def _check_header_map_keys_exist(header_map, source_headers):
    unknown = set(header_map.keys()) - source_headers
    if unknown:
        raise ValidationError(
            f"header_map references headers not in source: {', '.join(sorted(unknown))}"
        )


def _check_header_map_covers_all(header_map, source_headers):
    uncovered = source_headers - set(header_map.keys())
    if uncovered:
        raise ValidationError(
            f"source columns not covered by header_map: {', '.join(sorted(uncovered))}"
        )


def _check_header_map_unique_values(header_map):
    seen = {}
    for source, target in header_map.items():
        if target is None:
            continue
        if target in seen:
            raise ValidationError(
                f"duplicate field name '{target}' mapped from both "
                f"'{seen[target]}' and '{source}'"
            )
        seen[target] = source


def _check_primary_key(fields):
    # Check for id: primary or any field with primary marker
    for name, spec in fields.items():
        if spec == "primary":
            return
        if isinstance(spec, dict) and spec.get("primary"):
            return
    raise ValidationError("no primary key defined in fields")


def _check_key_collisions(pipeline, keys, fields):
    all_keys = {}

    # Collect keys from pipeline inputs
    inputs = pipeline.get("inputs", {})
    for input_name, input_spec in inputs.items():
        if isinstance(input_spec, dict) and "key" in input_spec:
            key = input_spec["key"]
            if key in all_keys:
                raise ValidationError(
                    f"key collision: '{key}' used by both "
                    f"{all_keys[key]} and pipeline.inputs.{input_name}"
                )
            all_keys[key] = f"pipeline.inputs.{input_name}"

    # Collect keys from keys section
    for key_name, key_value in keys.items():
        if key_value in all_keys:
            raise ValidationError(
                f"key collision: '{key_value}' used by both "
                f"{all_keys[key_value]} and keys.{key_name}"
            )
        all_keys[key_value] = f"keys.{key_name}"

    # Collect keys from fields
    for field_name, field_spec in fields.items():
        if isinstance(field_spec, dict) and "key" in field_spec:
            key = field_spec["key"]
            if key in all_keys:
                raise ValidationError(
                    f"key collision: '{key}' used by both "
                    f"{all_keys[key]} and fields.{field_name}"
                )
            all_keys[key] = f"fields.{field_name}"


def _check_enum_integrity(fields, header_map, analysis):
    # Build lookup: field_name -> source column analysis
    col_by_header = {col["header"]: col for col in analysis["columns"]}
    field_to_source = {}
    for source_header, field_name in header_map.items():
        if field_name is not None:
            field_to_source[field_name] = col_by_header.get(source_header)

    for field_name, field_spec in fields.items():
        if not isinstance(field_spec, dict):
            continue
        if field_spec.get("type") != "enum":
            continue
        source_col = field_to_source.get(field_name)
        if source_col is None or source_col.get("values") is None:
            continue

        source_values = set(source_col["values"])
        field_values = set(field_spec.get("values", []))

        invented = field_values - source_values
        if invented:
            raise ValidationError(
                f"enum field '{field_name}' has invented values: "
                f"{', '.join(sorted(invented))}"
            )

        dropped = source_values - field_values
        if dropped:
            raise ValidationError(
                f"enum field '{field_name}' dropped values: "
                f"{', '.join(sorted(dropped))}"
            )


def _check_prompt_templates(pipeline, templates_dir):
    templates_path = Path(templates_dir)
    inputs = pipeline.get("inputs", {})
    for input_name, input_spec in inputs.items():
        if not isinstance(input_spec, dict):
            continue
        template_name = input_spec.get("prompt_template")
        if template_name is None:
            continue
        template_file = templates_path / f"{template_name}.md"
        if not template_file.exists():
            raise ValidationError(
                f"prompt template '{template_name}' referenced by "
                f"pipeline.inputs.{input_name} not found at {template_file}"
            )


def _check_type_compatibility(fields, header_map, analysis):
    col_by_header = {col["header"]: col for col in analysis["columns"]}
    field_to_source = {}
    for source_header, field_name in header_map.items():
        if field_name is not None:
            field_to_source[field_name] = col_by_header.get(source_header)

    for field_name, field_spec in fields.items():
        if not isinstance(field_spec, dict):
            continue
        target_type = field_spec.get("type")
        if target_type is None:
            continue
        source_col = field_to_source.get(field_name)
        if source_col is None:
            continue

        source_type = source_col["type"]
        allowed = COMPATIBLE_TYPES.get(source_type)
        if allowed is None:
            continue
        if target_type not in allowed:
            raise ValidationError(
                f"type incompatibility for field '{field_name}': "
                f"source type '{source_type}' cannot map to '{target_type}'"
            )
