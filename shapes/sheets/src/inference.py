import importlib
import json
import os
from pathlib import Path

import yaml

def resolve_backend(
    corpus_root: Path, sheet_dir: Path | None = None
) -> tuple[str, str]:
    """Resolve inference backend via: env var -> sheet.yaml -> moui.json. Raises if none configured."""
    env = os.environ.get("SHEETS_LLM")
    if env:
        if ":" in env:
            backend, model = env.split(":", 1)
            return backend, model
        return env, "default"

    if sheet_dir:
        sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
        inf = sheet.get("inference", {}).get("default")
        if inf:
            if isinstance(inf, str):
                return inf, "default"
            return inf["backend"], inf.get("model", "default")

    moui_path = Path(corpus_root) / "moui.json"
    if moui_path.exists():
        manifest = json.loads(moui_path.read_text())
        inf = manifest.get("inference", {}).get("default")
        if inf:
            if isinstance(inf, str):
                return inf, "default"
            return inf["backend"], inf.get("model", "default")

    raise ValueError(
        "No inference backend configured. Set SHEETS_LLM env var, "
        "add inference.default to sheet.yaml, or add inference.default to moui.json."
    )


def load_backend(backend_name: str):
    """Import and return the backend module."""
    module = importlib.import_module(
        f"shapes.sheets.src.backends.{backend_name}"
    )
    return module
