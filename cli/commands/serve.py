"""Handler for: mo <shape> serve <path>"""
import importlib.util
import inspect
import sys
from pathlib import Path

import yaml

from cli.moui import resolve_content_path
from cli.infra.targets import load_target, get_environment
from cli.infra.services import resolve_chat_binding


def resolve_dev_chat_config(corpus_root: Path, content_path, env_name: str,
                            chat_endpoint) -> dict | None:
    """Resolve the chat_config the dev server will hand the grove build.

    - grove has no chat feature → None (nothing to bind).
    - --chat-endpoint given → open chat, no gate; short-circuits target resolution.
    - else → resolve the deploy target's env and derive {endpoint, gate} the same
      way deploy does, but WITHOUT reading the secret (with_code=False)."""
    grove_file = Path(content_path) / "grove.yaml"
    if not grove_file.is_file():
        return None
    grove = yaml.safe_load(grove_file.read_text()) or {}
    has_chat = any(f.get("type") == "chat" for f in grove.get("features", []))
    if not has_chat:
        return None

    if chat_endpoint:
        return {"endpoint": chat_endpoint, "gate": None}

    target = load_target(content_path, corpus_root)
    grove_env = get_environment(target, env_name)
    binding = resolve_chat_binding(grove, grove_env, env_name, corpus_root,
                                   with_code=False)
    return {"endpoint": binding["endpoint"], "gate": binding["gate"]}


def run(corpus_root: Path, instance: str, args: list) -> None:
    usage = (f"Usage: mo {instance} serve <path> "
             "[--chat-endpoint <url>] [--env <env>]")
    if not args:
        print(usage)
        sys.exit(1)

    chat_endpoint = None
    if "--chat-endpoint" in args:
        i = args.index("--chat-endpoint")
        if i + 1 >= len(args):
            print(usage, file=sys.stderr)
            sys.exit(1)
        chat_endpoint = args[i + 1]
        args = args[:i] + args[i + 2:]

    env_name = "dev"
    env_explicit = False
    if "--env" in args:
        i = args.index("--env")
        if i + 1 >= len(args):
            print(usage, file=sys.stderr)
            sys.exit(1)
        env_name = args[i + 1]
        env_explicit = True
        args = args[:i] + args[i + 2:]

    if chat_endpoint and env_explicit:
        print("--chat-endpoint and --env are mutually exclusive: "
              "--chat-endpoint is the open-chat poke, --env resolves the gated "
              "binding.", file=sys.stderr)
        sys.exit(1)

    content_path = resolve_content_path(Path(args[0]).resolve())

    from cli.loader import load_corpus, resolve_shape
    corpus = load_corpus(corpus_root)
    shape = resolve_shape(corpus, instance, corpus_root)

    # Enforce network permissions declared in the shape manifest
    network_perm = shape["manifest"].get("permissions", {}).get("network", "unrestricted")
    from cli.permissions import enforce_network
    enforce_network(network_perm)

    shape_type = shape["manifest"].get("type")
    if shape_type != "renderer":
        # Non-renderer shapes (e.g. sheets) may declare their own serve adapter
        from cli.moui import _run_shape_command
        _run_shape_command(corpus_root, instance, "serve", args)
        return

    from cli.constants import SHELL
    server_path = shape["path"] / "renderer" / SHELL

    spec = importlib.util.spec_from_file_location(
        f"{instance}.server",
        server_path / "server.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    serve_kwargs = {}
    if "chat_config" in inspect.signature(mod.serve).parameters:
        serve_kwargs["chat_config"] = resolve_dev_chat_config(
            corpus_root, content_path, env_name, chat_endpoint)
    mod.serve(content_path, shape["path"], corpus_root, **serve_kwargs)
