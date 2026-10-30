"""Load and validate exports.yaml configurations."""
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from shapes.sheets.src.locale import SUPPORTED_LOCALES

SUPPORTED_FORMATS = {"csv", "xlsx"}
ALLOWED_SUBSTITUTIONS = {"sheet", "date", "datetime", "format", "name"}
_SUBSTITUTION_RE = re.compile(r"\{(\w+)\}")


class ExportsError(Exception):
    pass


def load_exports(sheet_dir: Path) -> dict:
    exports_path = sheet_dir / "exports.yaml"
    if not exports_path.exists():
        raise ExportsError(f"exports.yaml not found in {sheet_dir}")
    data = yaml.safe_load(exports_path.read_text())
    if not data or "exports" not in data:
        raise ExportsError("exports.yaml must contain an 'exports' key")
    return data["exports"]


def validate_exports(exports: dict, field_names: list[str]) -> None:
    for name, config in exports.items():
        _validate_entry(name, config, field_names)


def _validate_entry(name: str, config: dict, field_names: list[str]) -> None:
    if "formats" not in config:
        raise ExportsError(f"Export '{name}': 'formats' is required")
    for fmt in config["formats"]:
        if fmt not in SUPPORTED_FORMATS:
            raise ExportsError(
                f"Export '{name}': Unknown format '{fmt}'. "
                f"Supported: {sorted(SUPPORTED_FORMATS)}"
            )
    if "fields" in config:
        for field in config["fields"]:
            if field not in field_names:
                raise ExportsError(
                    f"Export '{name}': Unknown field '{field}'. "
                    f"Known fields: {field_names}"
                )
    if "locale" in config:
        if config["locale"] not in SUPPORTED_LOCALES:
            raise ExportsError(
                f"Export '{name}': Unknown locale '{config['locale']}'. "
                f"Supported: {SUPPORTED_LOCALES}"
            )
    if "output" in config:
        path = config["output"]
        used = set(_SUBSTITUTION_RE.findall(path))
        unknown = used - ALLOWED_SUBSTITUTIONS
        if unknown:
            raise ExportsError(
                f"Export '{name}': Unknown substitution(s) "
                f"{{{', '.join(sorted(unknown))}}}. "
                f"Allowed: {{{', '.join(sorted(ALLOWED_SUBSTITUTIONS))}}}"
            )
        if len(config["formats"]) > 1 and "{" in path and "format" not in used:
            raise ExportsError(
                f"Export '{name}': output template with multiple formats "
                f"must contain {{format}} to avoid clobbering"
            )


def resolve_output_path(
    export_name: str,
    export_config: dict,
    sheet_dir: Path,
    sheet_name: str,
    fmt: str,
) -> Path:
    output = export_config.get("output")
    if output is None:
        return sheet_dir / "exports" / export_name / f"{sheet_name}.{fmt}"
    expanded = Path(output).expanduser()
    if "{" not in output:
        return expanded / f"{sheet_name}.{fmt}"
    now = datetime.now(timezone.utc)
    substitutions = {
        "sheet": sheet_name,
        "date": now.strftime("%Y-%m-%d"),
        "datetime": now.strftime("%Y-%m-%dT%H-%M"),
        "format": fmt,
        "name": export_name,
    }
    resolved = str(expanded)
    for key, value in substitutions.items():
        resolved = resolved.replace(f"{{{key}}}", value)
    return Path(resolved)
