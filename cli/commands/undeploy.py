"""Handler for: mo undeploy <content-path> <environment> [--force]

Removes deployed content from a configured remote.
Reads infrastructure/targets/ for deployment topology.
Reads infrastructure/remotes.yaml for remote configuration.
Calls adapter.unpublish() to remove content from the remote.
Cleans up .corpus/publishes/ state file.
"""
import inspect
import sys
from pathlib import Path

from cli.moui import resolve_content_path
from cli.infra.remotes import load_remotes, get_remote
from cli.infra.targets import load_target, get_environment, validate_remote_refs
from cli.infra.resolver import resolve_credentials
from cli.commands.deploy import _load_adapter, _build_config_for_adapter


def _state_path(corpus_root: Path, content_path: Path) -> Path:
    rel = content_path.relative_to(corpus_root / "content")
    if content_path.is_dir():
        return corpus_root / ".corpus" / "publishes" / rel.with_suffix(".yaml")
    return corpus_root / ".corpus" / "publishes" / rel


def run(corpus_root: Path, _instance, args: list) -> None:
    """Entry point for mo undeploy.

    Usage: mo undeploy <content-path> <environment> [--force]
    """
    force = False

    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--force":
            force = True
            i += 1
        elif not args[i].startswith("--"):
            positional.append(args[i])
            i += 1
        else:
            i += 1

    if len(positional) < 2:
        print("Usage: mo undeploy <content-path> <environment> [--force]")
        sys.exit(1)

    path_arg, env_name = positional[0], positional[1]

    content_path = resolve_content_path(Path(path_arg).resolve())
    remotes = load_remotes(corpus_root)
    target = load_target(content_path, corpus_root)
    validate_remote_refs(target, remotes)
    env = get_environment(target, env_name)
    remote = get_remote(remotes, env["remote"])
    publish_path = env["publish_path"]

    from cli.output import header, detail, done

    header("Undeploying:", str(content_path.relative_to(corpus_root)))
    detail("Env:", env_name)
    detail("Remote:", env["remote"])
    detail("Publish path:", publish_path)

    # Resolve credentials and build adapter config
    credentials = resolve_credentials(remote, env["remote"], corpus_root)
    config = _build_config_for_adapter(remote, credentials, env)

    # Unpublish
    adapter_mod = _load_adapter(corpus_root, remote["adapter"])
    unpublish_params = list(inspect.signature(adapter_mod.unpublish).parameters.keys())
    unpublish_kwargs = {}
    if "force" in unpublish_params:
        unpublish_kwargs["force"] = force
    adapter_mod.unpublish(config, publish_path, **unpublish_kwargs)

    # Clean up state file
    sp = _state_path(corpus_root, content_path)
    if sp.exists():
        sp.unlink()
        detail("State:", f"removed {sp.relative_to(corpus_root)}")

    done()
