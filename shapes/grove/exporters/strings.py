"""System strings loader — same cascade as tokens (dark overrides default)."""
from __future__ import annotations

from pathlib import Path
import yaml


class MissingStringsError(Exception):
    """Raised when theme strings.yaml is missing required keys."""

    def __init__(self, strings_path: Path, missing_keys: list[str], catalog_path: Path):
        self.strings_path = strings_path
        self.missing_keys = missing_keys
        self.catalog_path = catalog_path
        keys_list = "\n".join(f"  - {k}" for k in sorted(missing_keys))
        super().__init__(
            f"MissingStringsError: {strings_path} is missing {len(missing_keys)} keys:\n"
            f"{keys_list}\n"
            f"Reference: {catalog_path}"
        )


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _reference_keys(languages_dir: Path) -> tuple[set[str], Path]:
    """Load the first catalog file to get the set of required keys."""
    for path in sorted(languages_dir.iterdir()):
        if path.suffix in (".yaml", ".yml"):
            data = _load_yaml(path)
            return set(data.keys()), path
    raise FileNotFoundError(f"No language files found in {languages_dir}")


def load_strings(themes_dir: Path, languages_dir: Path, extra_required=()) -> dict:
    """Load strings from theme with dark-overrides-default cascade.

    Validates that all keys from the engine catalog — plus any `extra_required`
    keys a declared feature demands (e.g. the chat feature's strings, required
    only for groves that use it) — are present. Raises FileNotFoundError if
    default/strings.yaml is missing. Raises MissingStringsError listing all
    missing keys in one pass.
    """
    default_path = themes_dir / "default" / "strings.yaml"
    if not default_path.exists():
        raise FileNotFoundError(f"Strings not found: {default_path}")

    strings = _load_yaml(default_path)

    dark_path = themes_dir / "dark" / "strings.yaml"
    if dark_path.exists():
        dark_strings = _load_yaml(dark_path)
        strings = {**strings, **dark_strings}

    required_keys, catalog_path = _reference_keys(languages_dir)
    required_keys = required_keys | set(extra_required)
    missing = required_keys - set(strings.keys())
    if missing:
        raise MissingStringsError(default_path, list(missing), catalog_path)

    return strings
