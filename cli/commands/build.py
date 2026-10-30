"""Handler for: mo <shape> build <path> [--encrypted] [--rotate]"""
import sys
from pathlib import Path

from cli.moui import resolve_content_path


def _mnemonic_state_path(content_path: Path, corpus_root: Path) -> Path:
    """Derive path for mnemonic persistence."""
    rel = content_path.relative_to(corpus_root / "content")
    if content_path.is_dir():
        return corpus_root / ".corpus" / "publishes" / rel.with_suffix(".yaml")
    return corpus_root / ".corpus" / "publishes" / rel


def _load_mnemonic(state_path: Path) -> str | None:
    if not state_path.exists():
        return None
    import yaml
    data = yaml.safe_load(state_path.read_text()) or {}
    return data.get("mnemonic")


def _save_mnemonic(state_path: Path, mnemonic: str, content_path: Path, corpus_root: Path) -> None:
    import yaml
    data = {}
    if state_path.exists():
        data = yaml.safe_load(state_path.read_text()) or {}
    data["mnemonic"] = mnemonic
    data["encrypted"] = True
    if not data.get("content"):
        data["content"] = str(content_path.relative_to(corpus_root))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def run(corpus_root: Path, instance: str, args: list) -> None:
    if not args:
        print(f"Usage: mo {instance} build <path> [--encrypted] [--rotate]")
        sys.exit(1)

    encrypted = "--encrypted" in args
    rotate = "--rotate" in args
    path_args = [a for a in args if not a.startswith("--")]

    if not path_args:
        print(f"Usage: mo {instance} build <path> [--encrypted] [--rotate]")
        sys.exit(1)

    content_path = resolve_content_path(Path(path_args[0]).resolve())

    # If encrypted, try to load existing mnemonic from state file
    existing_mnemonic = None
    if encrypted and not rotate:
        state_path = _mnemonic_state_path(content_path, corpus_root)
        existing_mnemonic = _load_mnemonic(state_path)

    # Load shape build module (same pattern as deploy.py)
    import importlib.util
    exporters_dir = corpus_root / "shapes" / instance / "exporters"
    build_file = exporters_dir / "build.py"
    if not build_file.exists():
        print(f"No build module at {build_file}")
        sys.exit(1)

    if str(exporters_dir) not in sys.path:
        sys.path.insert(0, str(exporters_dir))

    spec = importlib.util.spec_from_file_location(f"{instance}_build", build_file)
    build_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_mod)

    # Each shape's build() has its own positional signature. Inspect to route.
    import inspect
    sig = inspect.signature(build_mod.build)
    params = list(sig.parameters.keys())

    build_kwargs = {"encrypted": encrypted, "mnemonic": existing_mnemonic, "rotate": rotate}
    if "crawlable" in params:
        build_kwargs["crawlable"] = "thin"
    if "instance_name" in params:
        # deck: build(content_path, instance_name, corpus_root, ...)
        result = build_mod.build(content_path, instance, corpus_root, **build_kwargs)
    else:
        # grove: build(grove_root, corpus_root, *, base_url, ...)
        # Standalone build uses localhost placeholder — canonical URL comes from deploy targets.
        result = build_mod.build(content_path, corpus_root, base_url="http://localhost:4200", **build_kwargs)
    if isinstance(result, tuple):
        build_dir, mnemonic = result
    else:
        build_dir, mnemonic = result, None

    # Save mnemonic to state file so it persists across builds and deploys
    if mnemonic:
        state_path = _mnemonic_state_path(content_path, corpus_root)
        _save_mnemonic(state_path, mnemonic, content_path, corpus_root)

    from cli.output import header, detail, output_file, output_dir, done
    mode = "encrypted" if encrypted else "plain"
    header("Building:", content_path.name if hasattr(content_path, 'name') else str(content_path))
    detail("Mode:", mode)
    if mnemonic:
        detail("Access code:", mnemonic)
    output_file(str(build_dir))
    output_dir(str(build_dir.parent))
    done()
