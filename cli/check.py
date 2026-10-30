"""moui check — validate corpus and shapes.

Validates:
  Corpus: moui.json against schema/manifest.v1.json
  Per-shape: shape.manifest.yaml against schema/shape.v1.json
  Per-shape: schema deposits in content/schema/
  Content: metadata instance, schema, and theme references resolve

Usage:
  moui check [--shape <instance>] [--fast]

  --shape   Run checks for a single shape instance only.
  --fast    Skip content metadata scan.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml

from cli.component_resolver import resolve_component, collect_component_refs
from cli.loader import load_corpus, resolve_all_shapes, resolve_shape


def validate_corpus_manifest(corpus_root: Path) -> list[str]:
    """Validate moui.json against schema/manifest.v1.json."""
    errors = []
    schema_path = corpus_root / "schema" / "manifest.v1.json"
    moui_path = corpus_root / "moui.json"

    if not schema_path.exists():
        return [f"Missing schema: {schema_path}"]
    if not moui_path.exists():
        return [f"Missing moui.json at {moui_path}"]

    schema = json.loads(schema_path.read_text())
    instance = json.loads(moui_path.read_text())

    try:
        jsonschema.validate(instance, schema)
    except jsonschema.ValidationError as e:
        errors.append(f"moui.json validation error: {e.message}")

    return errors


def validate_shape_manifests(corpus_root: Path) -> list[str]:
    """Validate each shape.manifest.yaml against schema/shape.v1.json."""
    errors = []
    schema_path = corpus_root / "schema" / "shape.v1.json"
    if not schema_path.exists():
        return [f"Missing schema: {schema_path}"]

    schema = json.loads(schema_path.read_text())
    corpus = load_corpus(corpus_root)

    for instance_name in corpus["shapes"]:
        try:
            shape = resolve_shape(corpus, instance_name, corpus_root)
        except (FileNotFoundError, KeyError) as e:
            errors.append(str(e))
            continue

        try:
            jsonschema.validate(shape["manifest"], schema)
        except jsonschema.ValidationError as e:
            errors.append(f"[{instance_name}] shape.manifest.yaml: {e.message}")

    return errors


def validate_schema_deposits(corpus_root: Path) -> list[str]:
    """Check that each shape's declared schema deposits exist in content/schema/.

    Fails hard if a manifest is missing the schemas block or the defines field.
    """
    errors = []
    corpus = load_corpus(corpus_root)
    content_schema_dir = corpus_root / "content" / "schema"

    for instance_name in corpus["shapes"]:
        try:
            shape = resolve_shape(corpus, instance_name, corpus_root)
        except (FileNotFoundError, KeyError) as e:
            errors.append(str(e))
            continue

        manifest = shape["manifest"]
        schemas_block = manifest.get("schemas")
        if schemas_block is None:
            errors.append(f"[{instance_name}] shape.manifest.yaml: missing 'schemas' block")
            continue

        defines = schemas_block.get("defines")
        if defines is None:
            errors.append(f"[{instance_name}] shape.manifest.yaml: missing 'schemas.defines' field")
            continue

        for schema_name in defines:
            deposit_path = content_schema_dir / schema_name
            if not deposit_path.exists():
                errors.append(f"[{instance_name}] Missing schema deposit: {deposit_path}")

    return errors


def validate_content_metadata(corpus_root: Path) -> list[str]:
    """Scan content files and validate instance, schema, and theme references.

    Any file identified as a bite (has instance) must also have schema.
    theme is optional.
    """
    errors = []
    content_dir = corpus_root / "content"
    if not content_dir.exists():
        return errors

    corpus = load_corpus(corpus_root)
    installed = set(corpus["shapes"].keys())

    shapes = {}
    for instance_name in corpus["shapes"]:
        try:
            shapes[instance_name] = resolve_shape(corpus, instance_name, corpus_root)
        except (FileNotFoundError, KeyError) as e:
            errors.append(f"[{instance_name}] {e}")

    content_schema_dir = (corpus_root / "content" / "schema").resolve()

    for path in content_dir.rglob("*"):
        if path.is_dir():
            continue
        if path.parent.resolve() == content_schema_dir:
            continue

        metadata = _extract_metadata(path)
        if metadata is None:
            continue

        rel = path.relative_to(corpus_root)

        # Validate instance reference
        instance_ref = metadata.get("instance")
        if instance_ref and instance_ref not in installed:
            errors.append(f"[{rel}] instance '{instance_ref}' not in moui.json")

        # Validate schema is present and resolves
        schema_ref = metadata.get("schema")
        if not schema_ref:
            errors.append(f"[{rel}] missing required 'schema' field")
        elif not (corpus_root / "content" / "schema" / schema_ref).exists():
            errors.append(f"[{rel}] schema '{schema_ref}' not found in content/schema/")

        # Validate theme reference — must be a relative path that resolves to a directory
        theme_ref = metadata.get("theme")
        if theme_ref:
            theme_dir = (path.parent / theme_ref).resolve()
            if not theme_dir.is_dir():
                errors.append(
                    f"[{rel}] theme directory not found: {theme_dir} "
                    f"(resolved from '{theme_ref}')"
                )
            elif not (theme_dir / "tokens.yaml").exists():
                errors.append(
                    f"[{rel}] tokens.yaml not found in theme directory: {theme_dir}"
                )

    return errors


def _extract_metadata(path: Path) -> dict | None:
    """Extract metadata from a content file. Returns None if not a bite."""
    if path.suffix == ".md":
        return _extract_frontmatter(path)
    elif path.suffix in (".yaml", ".yml"):
        if path.name.endswith(".asset.yaml"):
            return None
        try:
            data = yaml.safe_load(path.read_text())
            if isinstance(data, dict) and "instance" in data:
                return data
        except yaml.YAMLError:
            pass
    return None


def _extract_frontmatter(path: Path) -> dict | None:
    """Extract YAML frontmatter from a Markdown file."""
    try:
        text = path.read_text()
    except (UnicodeDecodeError, PermissionError):
        return None

    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        metadata = yaml.safe_load(parts[1])
        if isinstance(metadata, dict) and "instance" in metadata:
            return metadata
    except yaml.YAMLError:
        pass

    return None


def validate_components(corpus_root: Path) -> list[str]:
    """Validate component references in content files.

    For each deck that references a component:
    1. Check the component directory exists (resolution chain)
    2. Check component.yaml is valid
    3. If component declares theme-requires, verify the deck's theme defines them
    """
    errors = []
    content_dir = corpus_root / "content"
    if not content_dir.exists():
        return errors

    corpus = load_corpus(corpus_root)

    for path in content_dir.rglob("*"):
        if path.is_dir() or path.suffix not in (".yaml", ".yml"):
            continue
        if path.parent.resolve() == (corpus_root / "content" / "schema").resolve():
            continue

        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict) or "instance" not in data:
            continue

        component_refs = collect_component_refs(data)
        if not component_refs:
            continue

        rel = path.relative_to(corpus_root)
        instance_name = data["instance"]
        shape_path = corpus_root / "shapes" / instance_name

        theme_ref = data.get("theme")
        theme_tokens = None
        if theme_ref:
            theme_dir = (path.parent / theme_ref).resolve()
            tokens_path = theme_dir / "tokens.yaml"
            if tokens_path.exists():
                theme_tokens = yaml.safe_load(tokens_path.read_text())

        for comp_name in component_refs:
            try:
                comp_dir = resolve_component(
                    comp_name, corpus_root=corpus_root, shape_path=shape_path,
                )
            except FileNotFoundError:
                errors.append(f"[{rel}] component '{comp_name}' not found")
                continue

            comp_yaml = yaml.safe_load((comp_dir / "component.yaml").read_text())
            theme_requires = comp_yaml.get("theme-requires", [])

            if theme_requires and theme_tokens:
                for token in theme_requires:
                    if token not in theme_tokens:
                        errors.append(
                            f"[{rel}] component '{comp_name}' requires theme token "
                            f"'{token}' but theme '{theme_name}' does not define it"
                        )

    return errors


def validate_token_collisions(tokens: dict, theme_name: str) -> list[str]:
    """Check for token name collisions across gradients, palette, and borders namespaces."""
    gradients = set(tokens.get('gradients', {}).keys())
    palette = set(tokens.get('palette', {}).keys())
    borders = set(tokens.get('borders', {}).keys())
    errors = []
    for name in gradients & palette:
        errors.append(f'Theme "{theme_name}": token "{name}" exists in both gradients and palette')
    for name in gradients & borders:
        errors.append(f'Theme "{theme_name}": token "{name}" exists in both gradients and borders')
    for name in palette & borders:
        errors.append(f'Theme "{theme_name}": token "{name}" exists in both palette and borders')
    return errors


def validate_theme_tokens(corpus_root: Path) -> list[str]:
    """Check all content-referenced theme tokens for namespace collisions."""
    errors = []
    content_root = corpus_root / "content"
    if not content_root.is_dir():
        return errors
    seen_dirs: set[Path] = set()
    for path in content_root.rglob("*.yaml"):
        if path.name.endswith(".asset.yaml"):
            continue
        try:
            data = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        theme_ref = data.get("theme")
        if not theme_ref:
            continue
        theme_dir = (path.parent / theme_ref).resolve()
        if theme_dir in seen_dirs:
            continue
        seen_dirs.add(theme_dir)
        tokens_path = theme_dir / "tokens.yaml"
        if not tokens_path.exists():
            continue
        tokens = yaml.safe_load(tokens_path.read_text())
        rel = theme_dir.relative_to(corpus_root) if theme_dir.is_relative_to(corpus_root) else theme_dir
        errors.extend(validate_token_collisions(tokens, str(rel)))
    return errors


_PAGE_BUILTINS = {"grid", "list", "archive", "search"}


def validate_grove_pages(corpus_root: Path) -> list[str]:
    """Validate each grove's declared pages: map against page.v1.json.

    Discovers groves by finding grove.yaml files under content/. For each grove,
    reads its `pages:` map (route -> folder). Groves with no `pages:` map are skipped.
    For each declared entry:
      - The folder must exist and contain page.yaml.
      - page.yaml must validate against page.v1.json (home route '/' gets title injected
        from grove title before validation, mirroring the loader).
      - Each body ref is checked: elements/<name> -> <grove>/elements/<name>/index.html;
        self -> <grove>/<folder>/index.html; {feature: id} -> id in grove features;
        bare string is a built-in in _PAGE_BUILTINS or raises an error.
    """
    errors = []
    content_dir = corpus_root / "content"
    if not content_dir.exists():
        return errors

    schema_path = corpus_root / "content" / "schema" / "page.v1.json"
    if not schema_path.exists():
        return [f"Missing schema deposit: {schema_path}"]

    schema = json.loads(schema_path.read_text())

    for grove_yaml_path in sorted(content_dir.rglob("grove.yaml")):
        try:
            grove = yaml.safe_load(grove_yaml_path.read_text())
        except yaml.YAMLError as exc:
            errors.append(f"[{grove_yaml_path.relative_to(corpus_root)}] YAML parse error: {exc}")
            continue

        if not isinstance(grove, dict):
            continue

        pages_map = grove.get("pages")
        if not pages_map:
            continue  # no pages declared — no-op
        if not isinstance(pages_map, dict):
            errors.append(
                f"[{grove_yaml_path.relative_to(corpus_root)}] 'pages' must be a route->folder mapping"
            )
            continue

        grove_root = grove_yaml_path.parent
        grove_features = {f["id"] for f in grove.get("features", []) if isinstance(f, dict) and "id" in f}

        for route, location in pages_map.items():
            label = f"page '{route}'"

            if not isinstance(location, str):
                errors.append(f"[{label}] folder location must be a string, got {location!r}")
                continue

            folder = grove_root / location
            if not folder.is_dir():
                errors.append(f"[{label}] folder '{location}' not found under {grove_root.relative_to(corpus_root)}")
                continue

            page_yaml_path = folder / "page.yaml"
            if not page_yaml_path.is_file():
                errors.append(f"[{label}] missing page.yaml in '{location}'")
                continue

            try:
                data = yaml.safe_load(page_yaml_path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                errors.append(f"[{label}] YAML parse error: {exc}")
                continue

            if not isinstance(data, dict):
                errors.append(f"[{label}] page.yaml must be a mapping")
                continue

            # Mirror the loader: inject title for home route before validating
            if route == "/" and "title" not in data:
                data = {**data, "title": grove.get("title", "")}

            try:
                jsonschema.validate(data, schema)
            except jsonschema.ValidationError as exc:
                errors.append(f"[{label}] page.yaml validation error: {exc.message}")

            # Validate body refs
            body = data.get("body", ["self"])
            if not isinstance(body, list):
                errors.append(f"[{label}] 'body' must be a list")
                continue

            for ref in body:
                if isinstance(ref, str):
                    if ref == "self":
                        if not (folder / "index.html").exists():
                            errors.append(f"[{label}] body ref 'self' requires {location}/index.html")
                    elif ref.startswith("elements/"):
                        elem_name = ref[len("elements/"):]
                        elem_path = grove_root / "elements" / elem_name / "index.html"
                        if not elem_path.exists():
                            errors.append(f"[{label}] body ref '{ref}': elements/{elem_name}/index.html not found")
                    elif ref in _PAGE_BUILTINS:
                        pass  # known built-in, always valid
                    else:
                        errors.append(f"[{label}] body ref '{ref}' is not a built-in, 'self', or elements/<name>")
                elif isinstance(ref, dict):
                    feature_id = ref.get("feature")
                    if feature_id is not None:
                        if feature_id not in grove_features:
                            errors.append(
                                f"[{label}] body ref {{feature: {feature_id!r}}} not in grove features"
                            )
                    # other dict shapes (e.g. grid: {limit: 6}) are built-in configs — validated as-is

    return errors


def run_check(corpus_root: Path, args: list[str]) -> int:
    """Run moui check. Returns 0 on success, 1 on failure."""
    shape_filter = None
    fast = False
    i = 0
    while i < len(args):
        if args[i] == "--shape" and i + 1 < len(args):
            shape_filter = args[i + 1]
            i += 2
        elif args[i] == "--fast":
            fast = True
            i += 1
        else:
            print(f"Unknown argument: {args[i]}")
            return 1

    if shape_filter:
        corpus = load_corpus(corpus_root)
        if shape_filter not in corpus["shapes"]:
            print(f"FAIL: Shape instance '{shape_filter}' not found in moui.json")
            return 1

    all_errors = []

    # Corpus manifest
    if not shape_filter:
        errors = validate_corpus_manifest(corpus_root)
        _report("Corpus manifest", errors)
        all_errors.extend(errors)

    # Shape manifests
    errors = validate_shape_manifests(corpus_root)
    if shape_filter:
        errors = [e for e in errors if f"[{shape_filter}]" in e]
    _report("Shape manifests", errors)
    all_errors.extend(errors)

    # Schema deposits
    errors = validate_schema_deposits(corpus_root)
    if shape_filter:
        errors = [e for e in errors if f"[{shape_filter}]" in e]
    _report("Schema deposits", errors)
    all_errors.extend(errors)

    # Content metadata (skip if --fast)
    if not fast:
        errors = validate_content_metadata(corpus_root)
        _report("Content metadata", errors)
        all_errors.extend(errors)

    # Component validation (skip if --fast)
    if not fast:
        errors = validate_components(corpus_root)
        _report("Components", errors)
        all_errors.extend(errors)

    # Theme token namespace collisions
    errors = validate_theme_tokens(corpus_root)
    _report("Theme tokens", errors)
    all_errors.extend(errors)

    # Grove pages
    if not fast:
        errors = validate_grove_pages(corpus_root)
        _report("Grove pages", errors)
        all_errors.extend(errors)

    if all_errors:
        print(f"\nFAIL: {len(all_errors)} error(s) found")
        return 1
    else:
        print("\nOK: All checks passed")
        return 0


def _report(section: str, errors: list[str]):
    """Print check results for a section."""
    if errors:
        print(f"  FAIL  {section}")
        for err in errors:
            print(f"        {err}")
    else:
        print(f"  OK    {section}")
