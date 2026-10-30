"""Dependency resolution for shape capabilities.

Reads the dependencies block from a shape manifest and checks whether
Python packages are importable. Installs on demand when a capability
is first used.
"""
import importlib
import importlib.metadata
import re
import subprocess
import sys


def _parse_requirement(req: str) -> str:
    """Extract package name from a requirement string like 'pyyaml>=6.0'."""
    return re.split(r"[><=!~]", req)[0].strip()


def get_import_map(manifest: dict) -> dict:
    """Extract import_map from manifest. Returns empty dict if absent."""
    return manifest.get("dependencies", {}).get("python", {}).get("import_map", {})


def verify_import(import_name: str, pkg_name: str) -> bool:
    """Verify a package is importable. Returns True if import succeeds."""
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def check_capability_deps(manifest: dict, capability: str) -> list[str]:
    """Check if Python deps for a capability are installed.

    Returns a list of missing requirement strings (empty if all present).
    """
    deps = manifest.get("dependencies", {}).get("python", {})
    requirements = deps.get(capability, [])
    missing = []
    for req in requirements:
        pkg_name = _parse_requirement(req)
        try:
            importlib.metadata.version(pkg_name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(req)
    return missing


def _install_deps(requirements: list[str]) -> None:
    """Install missing Python packages into the running interpreter's environment."""
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", *requirements],
    )
    # Invalidate cached metadata so subsequent checks see the new packages.
    importlib.invalidate_caches()


def ensure_capability_deps(manifest: dict, capability: str, label: str) -> None:
    """Check deps for a capability. Auto-install if missing."""
    missing = check_capability_deps(manifest, capability)
    if not missing:
        return
    pkg_display = ", ".join(_parse_requirement(r) for r in missing)
    print(f"{label} requires: {pkg_display}")
    print("Installing...")
    try:
        _install_deps(missing)
    except subprocess.CalledProcessError:
        raise SystemExit(
            f"Failed to install: {pkg_display}\n"
            f"Try manually: {sys.executable} -m pip install {' '.join(missing)}"
        )
    # Verify
    still_missing = check_capability_deps(manifest, capability)
    if still_missing:
        pkg_list = " ".join(still_missing)
        raise SystemExit(
            f"Installation succeeded but packages not found: {pkg_list}\n"
            f"Try manually: {sys.executable} -m pip install {pkg_list}"
        )
    print("Done.\n")


def format_deps_report(manifest: dict) -> str:
    """Format a dependency report for moui check --deps."""
    deps = manifest.get("dependencies", {}).get("python", {})
    lines = []
    for capability, requirements in sorted(deps.items()):
        statuses = []
        for req in requirements:
            pkg_name = _parse_requirement(req)
            try:
                version = importlib.metadata.version(pkg_name)
                statuses.append(f"{pkg_name} {version} ✓")
            except importlib.metadata.PackageNotFoundError:
                statuses.append(f"{pkg_name} — not installed")
        lines.append(f"    {capability}: {', '.join(statuses)}")
    return "\n".join(lines)
