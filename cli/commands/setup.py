"""Handler for: mo setup [--non-interactive]"""
import sys
from pathlib import Path

from cli.loader import load_corpus, resolve_all_shapes
from cli.output import _c, GREEN, RED, YELLOW, DIM, BOLD


def detect_environment() -> dict:
    """Detect the Python environment mo is running in.

    Returns dict with 'type' (pipx|venv|system) and 'path'.
    """
    executable = sys.executable
    prefix = sys.prefix

    if "pipx" in executable:
        return {"type": "pipx", "path": prefix}

    if prefix != sys.base_prefix:
        return {"type": "venv", "path": prefix}

    return {"type": "system", "path": prefix}


def _format_env_line(env: dict) -> str:
    """Format the environment detection line."""
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    return f"Python {version} · {env['path']} · {env['type']}"


def _print_optional_capabilities(shapes: dict) -> None:
    """Print optional (non-core) capability groups that aren't installed."""
    from cli.deps import check_capability_deps

    lines = []
    for name, shape in sorted(shapes.items()):
        python_deps = shape["manifest"].get("dependencies", {}).get("python", {})
        for cap in sorted(python_deps):
            if cap in ("core", "import_map"):
                continue
            missing = check_capability_deps(shape["manifest"], cap)
            if missing:
                lines.append(f"  {name} {cap:<20} — mo {name} install --all")

    if lines:
        print()
        print(f"{_c(BOLD, 'Optional capabilities not installed')}")
        for line in lines:
            print(line)


def run(corpus_root: Path, args: list) -> int:
    non_interactive = "--non-interactive" in args

    # Environment
    env = detect_environment()
    print()
    print(f"{_c(BOLD, 'Environment')}")
    print(f"  {_format_env_line(env)}")

    if env["type"] == "system":
        print(f"  {_c(YELLOW, 'Warning: running in system Python. Consider installing moui via pipx.')}")
        if not non_interactive:
            answer = input("  Continue anyway? [y/N] ").strip().lower()
            if answer != "y":
                return 1

    # Shapes
    print()
    print(f"{_c(BOLD, 'Shapes')}")

    corpus = load_corpus(corpus_root)
    shapes = resolve_all_shapes(corpus, corpus_root)
    any_failed = False

    from cli.commands.install import run as install_run

    for name in sorted(shapes):
        result = install_run(corpus_root, name, [])
        if result != 0:
            any_failed = True

    # Remotes
    print()
    print(f"{_c(BOLD, 'Remotes')}")
    if non_interactive:
        print("  skipped (non-interactive mode — run: mo remote setup)")
    else:
        try:
            from cli.commands import remote
            remote.run(corpus_root, ["setup", "--all"])
        except (SystemExit, Exception):
            print(f"  {_c(YELLOW, 'remote setup skipped (no remotes configured or setup failed)')}")

    # Optional capabilities
    _print_optional_capabilities(shapes)
    print()

    return 1 if any_failed else 0
