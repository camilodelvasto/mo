"""Handler for: mo <shape> export <path> --format <pdf|pptx>"""
import importlib.util
import sys
from pathlib import Path

from cli.moui import resolve_content_path


def run(corpus_root: Path, instance: str, args: list) -> None:
    fmt = None
    path_arg = None

    i = 0
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        elif not args[i].startswith("--"):
            path_arg = args[i]
            i += 1
        else:
            i += 1

    if not path_arg or not fmt:
        print(f"Usage: mo {instance} export <path> --format <pdf|pptx>")
        sys.exit(1)

    if fmt not in ("pdf", "pptx"):
        print(f"Unsupported format: {fmt} (supported: pdf, pptx)")
        sys.exit(1)

    content_path = resolve_content_path(Path(path_arg).resolve())

    from cli.loader import load_corpus, resolve_shape
    corpus = load_corpus(corpus_root)
    shape = resolve_shape(corpus, instance, corpus_root)

    # Enforce network permissions declared in the shape manifest
    network_perm = shape["manifest"].get("permissions", {}).get("network", "unrestricted")
    from cli.permissions import enforce_network
    enforce_network(network_perm)

    # Check capability deps
    from cli.deps import ensure_capability_deps
    ensure_capability_deps(shape["manifest"], f"export.{fmt}", f"{fmt.upper()} export")

    # Derive output path
    from shapes.deck.exporters.build import derive_export_path
    export_dir = derive_export_path(content_path, instance, corpus_root)
    export_dir.mkdir(parents=True, exist_ok=True)
    output_path = export_dir / f"{content_path.stem}.{fmt}"

    # Load and call the exporter
    exporter_path = shape["path"] / "exporters" / f"{fmt}.py"
    if not exporter_path.exists():
        print(f"Exporter not found: {exporter_path}")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location(
        f"{instance}.exporters.{fmt}",
        exporter_path,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.export(content_path, shape["path"], corpus_root, output_path)

    from cli.output import header, detail, output_file, output_dir, note, done
    header("Exported:", content_path.name)
    detail("Format:", fmt.upper())
    output_file(str(result))
    output_dir(str(result.parent))
    if fmt == "pptx":
        note("Visual effects (shimmer, glow) are not reproduced in PPTX format.")
    done()
