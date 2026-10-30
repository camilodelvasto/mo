import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def scaffold_sheet(
    target: Path,
    corpus_root: Path,
    title: str | None = None,
) -> None:
    target = Path(target).resolve()
    corpus_root = Path(corpus_root).resolve()

    if target.exists() and any(target.iterdir()):
        print(
            f"Error: {target} exists and is not empty. Use --force to overwrite.",
            file=sys.stderr,
        )
        sys.exit(1)

    sheet_name = target.name
    if not title:
        title = sheet_name.replace("-", " ").replace("_", " ").title()

    moui_path = corpus_root / "moui.json"
    manifest = json.loads(moui_path.read_text())
    inference_default = manifest.get("inference", {}).get(
        "default", {"backend": "ollama", "model": "qwen3:8b"}
    )
    inference_str = json.dumps(inference_default) if isinstance(inference_default, dict) else inference_default

    variables = {
        "title": title,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "inference_default": inference_str,
    }

    target.mkdir(parents=True, exist_ok=True)
    (target / "prompts").mkdir(exist_ok=True)
    (target / "ingest" / "inbox").mkdir(parents=True, exist_ok=True)
    (target / "ingest" / "failed").mkdir(exist_ok=True)

    _copy_template(TEMPLATES_DIR / "sheet.template.yaml", target / "sheet.yaml", variables)
    _copy_template(TEMPLATES_DIR / "prompts" / "extract.template.md", target / "prompts" / "extract.md", variables)
    _copy_template(TEMPLATES_DIR / "prompts" / "update.template.md", target / "prompts" / "update.md", variables)
    _copy_template(TEMPLATES_DIR / "gitignore", target / ".gitignore", variables)
    _copy_template(TEMPLATES_DIR / "exports.template.yaml", target / "exports.yaml", variables)

    (target / "ops.jsonl").write_text("")
    (target / "ingest" / "journal.jsonl").write_text("")

    sheet = yaml.safe_load((target / "sheet.yaml").read_text())
    for key in ("title", "pipeline", "fields"):
        if key not in sheet:
            print(f"Error: scaffolded sheet.yaml missing required key: {key}", file=sys.stderr)
            sys.exit(1)

    relative_path = str(target.relative_to(corpus_root))

    print(f"Created sheet at {relative_path}")
    print()
    print("Next steps:")
    print(f"  1. Edit {relative_path}/sheet.yaml to define your fields")
    print(f"  2. Edit {relative_path}/prompts/extract.md")
    print(f"  3. Edit {relative_path}/prompts/update.md")
    print(f"  4. Run: mo sheets serve {sheet_name}")


def _copy_template(src: Path, dest: Path, variables: dict) -> None:
    content = src.read_text()
    for key, value in variables.items():
        content = content.replace(f"{{{{{key}}}}}", str(value))
    dest.write_text(content)
