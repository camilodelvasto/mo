"""Handler for: mo <shape> install [--all]"""
import sys
from pathlib import Path

from cli.deps import (
    _parse_requirement,
    get_import_map,
    _install_deps,
    verify_import,
)
from cli.loader import load_corpus, resolve_shape
from cli.output import _c, GREEN, RED


def run(corpus_root: Path, instance: str, args: list) -> int:
    install_all = "--all" in args

    corpus = load_corpus(corpus_root)
    shape = resolve_shape(corpus, instance, corpus_root)
    manifest = shape["manifest"]

    python_deps = manifest.get("dependencies", {}).get("python", {})
    import_map = get_import_map(manifest)

    # Collect capability groups to install
    if install_all:
        capabilities = [k for k in python_deps if k != "import_map"]
    else:
        capabilities = ["core"] if "core" in python_deps else []

    if not capabilities:
        print(f"  {instance}: no dependencies declared")
        return 0

    # Gather all requirements across selected capabilities
    all_requirements = []
    for cap in capabilities:
        all_requirements.extend(python_deps.get(cap, []))

    if not all_requirements:
        print(f"  {instance}: no dependencies declared")
        return 0

    # Check what's missing
    missing = []
    already_installed = []
    for req in all_requirements:
        pkg_name = _parse_requirement(req)
        import_name = import_map.get(pkg_name, pkg_name)
        if verify_import(import_name, pkg_name):
            already_installed.append(pkg_name)
        else:
            missing.append(req)

    if not missing:
        pkg_list = ", ".join(already_installed)
        print(f"  {instance} {_c(GREEN, '✓')}  already satisfied ({pkg_list})")
        return 0

    # Install missing
    pkg_display = ", ".join(_parse_requirement(r) for r in missing)
    print(f"  {instance}: installing {pkg_display}")
    try:
        _install_deps(missing)
    except Exception:
        print(f"  {instance} {_c(RED, '✗')}  failed to install: {pkg_display}")
        return 1

    # Verify via import
    failed = []
    installed = []
    for req in missing:
        pkg_name = _parse_requirement(req)
        import_name = import_map.get(pkg_name, pkg_name)
        if verify_import(import_name, pkg_name):
            installed.append(pkg_name)
        else:
            failed.append(pkg_name)

    if failed:
        fail_list = ", ".join(failed)
        print(f"  {instance} {_c(RED, '✗')}  installed but import failed: {fail_list}")
        return 1

    all_pkgs = already_installed + installed
    pkg_list = ", ".join(all_pkgs)
    count = len(installed)
    print(f"  {instance} {_c(GREEN, '✓')}  {count} package{'s' if count != 1 else ''} installed ({pkg_list})")
    return 0
