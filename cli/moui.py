#!/usr/bin/env python3
"""Moui CLI entry point. Parses argv and routes to command handlers."""
import importlib
import sys
from pathlib import Path

# find_corpus_root and resolve_content_path live here for now.
# Move to cli/utils.py if they grow or need independent testing.


def find_corpus_root() -> Path:
    """Walk up from cwd to find a directory containing moui.json.

    Adds the corpus root to sys.path so that shape modules (e.g.,
    shapes.deck.exporters.build) are importable by absolute path.
    """
    current = Path.cwd()
    while current != current.parent:
        if (current / "moui.json").exists():
            root_str = str(current)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
            return current
        current = current.parent
    raise FileNotFoundError("No moui.json found in current directory or any parent")


def resolve_content_path(path: Path) -> Path:
    """Resolve a content file path, inferring .yaml/.yml extension if needed.

    Tries: path as-is -> path.yaml -> path.yml. Returns first match.
    Raises FileNotFoundError if nothing matches.
    """
    if path.exists():
        return path
    for ext in (".yaml", ".yml"):
        candidate = path.with_suffix(ext)
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Content file not found: {path} (also tried .yaml, .yml)")


def _run_shape_command(corpus_root: Path, instance: str, subcommand: str, args: list):
    """Resolve and run a shape-specific command declared in the shape manifest."""
    import importlib.util
    from cli.loader import load_corpus, resolve_shape

    corpus = load_corpus(corpus_root)
    shape = resolve_shape(corpus, instance, corpus_root)
    capabilities = shape["manifest"].get("capabilities", {})

    if subcommand not in capabilities:
        print(f"Unknown command: mo {instance} {subcommand}")
        print(f"Shape '{instance}' does not declare a '{subcommand}' capability.")
        sys.exit(1)

    entries = capabilities[subcommand]
    if not entries or "adapter" not in entries[0]:
        print(f"Shape '{instance}' capability '{subcommand}' has no adapter.")
        sys.exit(1)

    adapter_path = shape["path"] / entries[0]["adapter"]
    if not adapter_path.exists():
        raise FileNotFoundError(f"Adapter not found: {adapter_path}")

    spec = importlib.util.spec_from_file_location(
        f"{instance}_{subcommand}", adapter_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "run"):
        raise AttributeError(f"Adapter {adapter_path} has no run() function")

    mod.run(corpus_root, instance, args)


def _shape_has_capability(corpus_root: Path, instance: str, subcommand: str) -> bool:
    """Check if a shape declares a capability with an adapter for this subcommand."""
    from cli.loader import load_corpus, resolve_shape
    try:
        corpus = load_corpus(corpus_root)
        shape = resolve_shape(corpus, instance, corpus_root)
        caps = shape["manifest"].get("capabilities", {})
        if subcommand in caps:
            entries = caps[subcommand]
            return bool(entries and "adapter" in entries[0])
    except (KeyError, FileNotFoundError):
        pass
    return False


HANDLERS = {
    "serve":     "cli.commands.serve",
    "build":     "cli.commands.build",
    "export":    "cli.commands.export_cmd",
    "install":   "cli.commands.install",
}

# Help text for top-level commands
TOP_LEVEL_HELP = {
    "deploy": (
        "Usage: mo deploy <content-path> <env> [--force] [--dry-run] [--no-chain] [--take-dns]\n\n"
        "Deploy built content to a configured remote.\n\n"
        "Examples:\n"
        "  mo deploy content/website/en codeberg/website\n"
        "  mo deploy content/moui/decks/pitch.yaml codeberg/decks --force"
    ),
    "remote": (
        "Usage: mo remote list|verify|setup <id>\n\n"
        "Manage infrastructure remotes and their credentials.\n\n"
        "Subcommands:\n"
        "  list                 Show all configured remotes and their status\n"
        "  verify <id>          Check credentials for a specific remote\n"
        "  setup <id>|--all     Interactively configure credentials"
    ),
    "reconcile": (
        "Usage: mo reconcile <remote-id> [--dry-run]\n\n"
        "Remove orphan deploy manifests from a remote.\n\n"
        "Scans all targets sharing the remote, builds the declared set of\n"
        "publish_paths, and removes any manifest in the repo not claimed by\n"
        "a current target. Use --dry-run to preview without pushing.\n\n"
        "Examples:\n"
        "  mo reconcile codeberg/moui-pages --dry-run\n"
        "  mo reconcile codeberg/moui-pages"
    ),
    "undeploy": (
        "Usage: mo undeploy <content-path> <env> [--force]\n\n"
        "Remove deployed content from a configured remote.\n\n"
        "Examples:\n"
        "  mo undeploy content/website/en prod\n"
        "  mo undeploy content/moui/decks/pitch.yaml prod --force"
    ),
    "check": (
        "Usage: mo check [--deps]\n\n"
        "Validate corpus structure, shape manifests, and schemas."
    ),
    "sync": (
        "Usage: mo sync <command> [args...]\n\n"
        "Sync workspace folders to git remotes.\n\n"
        "Subcommands:\n"
        "  init [--join <url>]     Set up or join a workspace\n"
        "  status [--watch]        Show sync state\n"
        "  push [folder]           Force sync\n"
        "  pull [folder]           Force pull\n"
        "  logs [--follow]         View sync log\n"
        "  daemon start|stop       Manage daemon"
    ),
    "setup": (
        "Usage: mo setup [--non-interactive]\n\n"
        "Install core dependencies for all active shapes and configure remotes.\n"
        "Use --non-interactive to skip credential prompts (for CI)."
    ),
}

# Help text for shape-prefixed commands
SHAPE_HELP = {
    "serve": (
        "Usage: mo <shape> serve <path>\n\n"
        "Serve a content file locally with live reload.\n\n"
        "Examples:\n"
        "  mo grove serve content/website/en/\n"
        "  mo deck serve content/moui/decks/pitch-deck.yaml"
    ),
    "build": (
        "Usage: mo <shape> build <path> [--encrypted] [--rotate]\n\n"
        "Build static output from a content file.\n\n"
        "Examples:\n"
        "  mo grove build content/website/en/\n"
        "  mo deck build content/moui/decks/pitch.yaml --encrypted"
    ),
    "export": (
        "Usage: mo <shape> export <path> --format <pdf|pptx>\n\n"
        "Export content to a document format.\n\n"
        "Examples:\n"
        "  mo deck export content/moui/decks/pitch.yaml --format pdf\n"
        "  mo deck export content/moui/decks/pitch.yaml --format pptx"
    ),
    "install": (
        "Usage: mo <shape> install [--all]\n\n"
        "Install Python dependencies declared in the shape manifest.\n"
        "Use --all to install optional capability deps (export, encryption).\n\n"
        "Examples:\n"
        "  mo grove install\n"
        "  mo deck install --all"
    ),
}


def _print_usage():
    """Print top-level usage and exit."""
    print("Usage:")
    print("  mo deploy <content-path> <env> [--force]    Deploy content to environment")
    print("  mo undeploy <content-path> <env> [--force]  Remove deployed content")
    print("  mo reconcile <remote-id> [--dry-run]       Remove orphan deploy manifests")
    print("  mo remote list|verify|setup                 Manage remotes")
    print("  mo check                                    Validate corpus and shapes")
    print("  mo setup [--non-interactive]                Onboard: install deps + configure remotes")
    print("  mo sync <command>                           Sync workspace folders")
    print("  mo <shape> serve <path>                     Serve a content file")
    print("  mo <shape> build <path>                     Build static output")
    print("  mo <shape> install [--all]                  Install shape dependencies")
    print("  mo <shape> <command> [args...]               Shape-specific commands")
    print()
    print("Run mo help <command> for details on a specific command.")


def _print_help(args: list):
    """Handle mo help, mo help <command>."""
    if not args:
        _print_usage()
        sys.exit(0)

    topic = args[0]
    if topic in TOP_LEVEL_HELP:
        print(TOP_LEVEL_HELP[topic])
        sys.exit(0)
    if topic in SHAPE_HELP:
        print(SHAPE_HELP[topic])
        sys.exit(0)

    print(f"Unknown command: {topic}")
    print()
    _print_usage()
    sys.exit(1)


def _print_shape_usage(corpus_root: Path, instance: str):
    """Print available commands for a shape, reading capabilities from its manifest."""
    from cli.loader import load_corpus, resolve_shape

    try:
        corpus = load_corpus(corpus_root)
        shape = resolve_shape(corpus, instance, corpus_root)
    except (KeyError, FileNotFoundError):
        print(f"Unknown shape: {instance}")
        return

    print(f"Usage: mo {instance} <command> [args...]")
    print()
    print("Commands:")

    # Generic commands available to all shapes
    for cmd in HANDLERS:
        if cmd in SHAPE_HELP:
            first_line = SHAPE_HELP[cmd].split("\n")[0]
            print(f"  {instance} {cmd:<12} {first_line}")
        else:
            print(f"  {instance} {cmd}")

    # Shape-specific capabilities with adapters
    capabilities = shape["manifest"].get("capabilities", {})
    for cap_name, entries in capabilities.items():
        if cap_name in HANDLERS:
            continue
        if entries and isinstance(entries[0], dict) and "adapter" in entries[0]:
            adapter_rel = entries[0]["adapter"]
            adapter_path = shape["path"] / adapter_rel
            doc = ""
            if adapter_path.exists():
                try:
                    first_lines = adapter_path.read_text().split("\n", 3)
                    for line in first_lines:
                        if line.startswith('"""') and len(line) > 3:
                            doc = line.strip('"').strip()
                            break
                except Exception:
                    pass
            if doc:
                print(f"  {instance} {cap_name:<12} {doc}")
            else:
                print(f"  {instance} {cap_name}")

    print()
    print(f"Run mo help <command> for details.")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        _print_usage()
        sys.exit(1)

    command = argv[0]
    args = argv[1:]

    # Help — check before anything else
    if command in ("help", "--help", "-h"):
        _print_help(args)

    # Top-level commands (no shape prefix)
    if command == "check":
        corpus_root = find_corpus_root()
        from cli.check import run_check
        sys.exit(run_check(corpus_root, args))
    elif command == "deploy":
        corpus_root = find_corpus_root()
        from cli.commands import deploy
        deploy.run(corpus_root, None, args)
    elif command == "undeploy":
        corpus_root = find_corpus_root()
        from cli.commands import undeploy
        undeploy.run(corpus_root, None, args)
    elif command == "reconcile":
        corpus_root = find_corpus_root()
        from cli.commands import reconcile
        reconcile.run(corpus_root, args)
    elif command == "remote":
        corpus_root = find_corpus_root()
        from cli.commands import remote
        remote.run(corpus_root, args)
    elif command == "setup":
        corpus_root = find_corpus_root()
        from cli.commands import setup
        sys.exit(setup.run(corpus_root, args))
    elif command == "sync":
        corpus_root = find_corpus_root()
        from cli.commands import sync
        sync.run(corpus_root, args)
    else:
        # Shape-prefixed commands: mo <shape> <command> [args...]
        instance = command
        if not args or args[0] in ("--help", "-h", "help"):
            corpus_root = find_corpus_root()
            _print_shape_usage(corpus_root, instance)
            sys.exit(1)

        subcommand = args[0]
        sub_args = args[1:]

        corpus_root = find_corpus_root()

        if _shape_has_capability(corpus_root, instance, subcommand):
            _run_shape_command(corpus_root, instance, subcommand, sub_args)
        elif subcommand in HANDLERS:
            module = importlib.import_module(HANDLERS[subcommand])
            module.run(corpus_root, instance, sub_args)
        else:
            print(f"Unknown command: mo {instance} {subcommand}")
            sys.exit(1)


if __name__ == "__main__":
    main()
