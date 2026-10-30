"""Handler for: mo deploy <content-path> <environment> [--force] [--dry-run] [--no-chain] [--take-dns]

Reads infrastructure/targets/ for deployment topology.
Reads infrastructure/remotes.yaml for remote configuration.
Resolves credentials per remote's credential key.
Builds with shape's build module, deploys via shared adapter.
"""
import base64
import importlib.util
import sys
from pathlib import Path

import yaml

from cli.moui import resolve_content_path
from cli.infra.remotes import load_remotes, get_remote
from cli.infra.targets import load_target, get_environment, derive_base_url, validate_remote_refs
from cli.infra.targets import declared_mounts
from cli.infra.dns import Dns, load_zones
from cli.infra.resolver import resolve_credentials
from cli.infra.services import resolve_chat_binding
from cli.infra.origin import origin_of
from cli.infra.chat_probe import probe_chat
from shapes.shared.adapters.outcome import Live, Staged


def _resolve_deploy(corpus_root: Path, content_path: Path, env_name: str):
    """Resolve target, environment, remote, and base_url for a deploy.

    No longer called from run() (the fork uses _resolve_spine, with base-url
    moved to the grove branch). Kept because tests reference it directly
    (test_deploy.py, test_deploy_chat_wiring.py); fold into a test refactor when
    derive_base_url's own coverage (test_targets.py) makes these redundant."""
    remotes = load_remotes(corpus_root)
    target = load_target(content_path, corpus_root)
    validate_remote_refs(target, remotes)
    env = get_environment(target, env_name)
    remote = get_remote(remotes, env["remote"])
    base_url = derive_base_url(env)
    return target, env, remote, base_url


def _resolve_spine(corpus_root: Path, ref, env_name: str):
    """Shared spine for both rails: where + who + the target. No base-url here —
    that is grove-only (a stack env has no base_path)."""
    remotes = load_remotes(corpus_root)
    target = load_target(ref, corpus_root)
    validate_remote_refs(target, remotes)
    env = get_environment(target, env_name)
    remote = get_remote(remotes, env["remote"])
    return target, env, remote


def _discriminator(target: dict) -> str:
    has_shape, has_stack = "shape" in target, "stack" in target
    if has_shape == has_stack:    # both or neither
        raise SystemExit("deploy target must declare exactly one of "
                         "shape: or stack:")
    return "stack" if has_stack else "shape"


def _load_adapter(corpus_root: Path, adapter_name: str):
    """Load adapter from shapes/shared/adapters/."""
    adapter_module_name = adapter_name.replace("-", "_")
    adapter_path = corpus_root / "shapes" / "shared" / "adapters" / f"{adapter_module_name}.py"
    if not adapter_path.exists():
        raise SystemExit(f"Adapter not found: {adapter_path}")

    spec = importlib.util.spec_from_file_location(
        f"shared.adapters.{adapter_module_name}",
        adapter_path,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# What the rail can inject: capability name -> builder(root, env, remote_id, take_dns).
_PROVIDERS = {
    "dns": lambda root, env, rid, take_dns: Dns(load_zones(root), take=take_dns),
    "declared_mounts": lambda root, env, rid, take_dns: declared_mounts(root, env["domain"]),
    "remote_id": lambda root, env, rid, take_dns: rid,
}
CAPABILITIES = tuple(_PROVIDERS)


def _check_capabilities(adapter_mod, remote_id: str, *, take_dns: bool) -> None:
    """Validate an adapter's REQUIRES against what the rail can inject, and
    --take-dns against it. Pure: builds nothing, touches nothing."""
    if not hasattr(adapter_mod, "REQUIRES"):
        raise SystemExit(f"adapter {adapter_mod.__name__} declares no REQUIRES — "
                         f"declare the capabilities it needs (REQUIRES = () for none)")
    requires = adapter_mod.REQUIRES
    if not isinstance(requires, tuple) or not all(isinstance(n, str) for n in requires):
        raise SystemExit(f"adapter {adapter_mod.__name__} REQUIRES must be a tuple of str, "
                         f"got {requires!r}")
    unknown = [n for n in requires if n not in CAPABILITIES]
    if unknown:
        raise SystemExit(f"adapter {adapter_mod.__name__} requires unknown "
                         f"capabilities: {unknown} (known: {sorted(CAPABILITIES)})")
    if take_dns and "dns" not in requires:
        raise SystemExit(f"--take-dns given, but remote {remote_id} "
                         f"({adapter_mod.__name__}) manages no DNS")


def _adapter_capabilities(corpus_root: Path, adapter_mod, env: dict, remote_id: str,
                          *, take_dns: bool) -> dict:
    """The capabilities an adapter declares in REQUIRES, built here and injected
    into its config — the adapter never imports a provider or reads targets."""
    _check_capabilities(adapter_mod, remote_id, take_dns=take_dns)
    return {n: _PROVIDERS[n](corpus_root, env, remote_id, take_dns)
            for n in adapter_mod.REQUIRES}


def _load_shape_build(corpus_root: Path, shape_name: str):
    """Load the shape's build module."""
    exporters_dir = corpus_root / "shapes" / shape_name / "exporters"
    build_file = exporters_dir / "build.py"
    if not build_file.exists():
        raise SystemExit(f"No build module at {build_file}")

    exporters_str = str(exporters_dir)
    if exporters_str not in sys.path:
        sys.path.insert(0, exporters_str)

    spec = importlib.util.spec_from_file_location(f"{shape_name}_build", build_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _state_path(corpus_root: Path, content_path: Path) -> Path:
    rel = content_path.relative_to(corpus_root / "content")
    if content_path.is_dir():
        return corpus_root / ".corpus" / "publishes" / rel.with_suffix(".yaml")
    return corpus_root / ".corpus" / "publishes" / rel


def _read_encryption_state(corpus_root: Path, shape_name: str, content_path: Path) -> tuple:
    """Read encrypted/mnemonic from .corpus/publishes/ state file."""
    sp = _state_path(corpus_root, content_path)
    if not sp.exists():
        return False, None
    import yaml
    data = yaml.safe_load(sp.read_text()) or {}
    return data.get("encrypted", False), data.get("mnemonic")


def _save_encryption_state(corpus_root: Path, content_path: Path, mnemonic: str) -> None:
    """Persist mnemonic to .corpus/publishes/ so subsequent deploys reuse it."""
    import yaml
    sp = _state_path(corpus_root, content_path)
    data = {}
    if sp.exists():
        data = yaml.safe_load(sp.read_text()) or {}
    data["mnemonic"] = mnemonic
    data["encrypted"] = True
    if not data.get("content"):
        data["content"] = str(content_path.relative_to(corpus_root))
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def _build_config_for_adapter(remote: dict, credentials: dict, env: dict) -> dict:
    """Merge remote config, credentials, and env domain into the adapter config dict.

    Adapters expect a flat config dict with keys like repo_url, branch,
    git_user, git_email (from remote) plus any credential-specific fields.
    The domain from the target environment is passed through so adapters can
    derive whether it's a custom domain.
    """
    config = {}
    # Map remote fields to adapter config fields
    if "repo" in remote:
        config["repo_url"] = remote["repo"]
    if "branch" in remote:
        config["branch"] = remote["branch"]
    if "git_user" in remote:
        config["git_user"] = remote["git_user"]
    if "git_email" in remote:
        config["git_email"] = remote["git_email"]
    # Server-based adapters
    if "host" in remote:
        config["host"] = remote["host"]
    if "user" in remote:
        config["user"] = remote["user"]
    if "path" in remote:
        config["path"] = remote["path"]
    # S3
    if "bucket" in remote:
        config["bucket"] = remote["bucket"]
    if "region" in remote:
        config["region"] = remote["region"]
    if "endpoint" in remote:
        config["endpoint"] = remote["endpoint"]
    # Domain from target environment — adapters derive custom domain from this
    config["domain"] = env["domain"]
    if env.get("aliases"):
        config["aliases"] = env["aliases"]
    # Merge credential values (e.g. token, ssh_key)
    config.update(credentials)
    return config


def _resolve_service_worker(env: dict, remote: dict, remote_id: str) -> bool:
    """Resolve the service-worker setting for a grove deploy.

    The remote declares the baseline (a service worker is a property of the
    hosting remote); a target environment may override it for a specific deploy
    (e.g. staging off). A remote that declares nothing is a misconfiguration —
    fail loud rather than imply a value (no silent default).
    """
    if "service_worker" not in remote:
        raise SystemExit(
            f"remote '{remote_id}' does not declare service_worker; "
            f"a grove-hosting remote must declare it (no silent default)"
        )
    return env.get("service_worker", remote["service_worker"])


def _ref_of(corpus_root: Path, path_arg: str):
    """Resolve a path_arg to either a direct ref string or a content Path.

    A direct target ref (e.g. 'clients/p/corpus') lives in
    infrastructure/targets/ and is passed through as-is.
    A content path (e.g. 'content/…' or an absolute path) is resolved
    via resolve_content_path.
    """
    direct = corpus_root / "infrastructure" / "targets" / f"{path_arg}.yaml"
    if direct.exists() and not path_arg.startswith("content/"):
        return path_arg
    return resolve_content_path(Path(path_arg).resolve())


def _refuse_take_dns_on_stack(take_dns: bool) -> None:
    if take_dns:
        raise SystemExit("--take-dns applies to grove deploys; a stack manages no DNS")


def _deploy_one(corpus_root: Path, ref, env_name: str, force: bool, dry_run: bool,
                *, take_dns: bool) -> None:
    """Deploy a single target (stack or grove) by ref.

    ref may be:
    - a direct infrastructure ref string (e.g. 'clients/p/corpus')
    - a content Path (resolved by resolve_content_path)
    load_target / _resolve_spine accept both forms.
    """
    target, env, remote = _resolve_spine(corpus_root, ref, env_name)
    kind = _discriminator(target)

    # Validate and build what the adapter needs before anything runs — a wrong
    # flag or a missing capability refuses before the build, and in dry-run.
    if kind == "stack":
        _refuse_take_dns_on_stack(take_dns)
    else:
        adapter_mod = _load_adapter(corpus_root, remote["adapter"])
        caps = _adapter_capabilities(corpus_root, adapter_mod, env, env["remote"],
                                     take_dns=take_dns)

    if dry_run:
        from cli.output import header, detail
        header("Deploy (dry-run):", str(ref))
        detail("  kind:", kind)
        detail("  env:", env_name)
        if env.get("remote"):
            detail("  remote:", env["remote"])
        if env.get("domain"):
            detail("  domain:", env["domain"])
        if take_dns:
            detail("  take-dns:", "yes")
        return

    if kind == "stack":
        from cli.deploy import stack
        stack.run(corpus_root, target, env, remote, env_name)
        return

    # ---- grove rail ----
    # ref may arrive as a content Path (resolved by the caller) or as a string.
    # For string refs: if the target has an explicit content: field, use that
    # (covers the case where _resolve_spine is mocked and returns a grove target
    # for an infra ref — the target dict carries the canonical content location).
    # Otherwise, resolve it as a content path.
    if isinstance(ref, Path):
        content_path = ref
    elif target.get("content"):
        content_path = corpus_root / "content" / target["content"]
    else:
        content_path = resolve_content_path(Path(ref).resolve())
    base_url = derive_base_url(env)
    shape_name = target["shape"]
    encrypted = env.get("encrypted", False)
    local_first = env.get("local_first", False)
    service_worker = _resolve_service_worker(env, remote, env["remote"])
    on_clear = env.get("on_clear", "reload")
    crawlable = env["crawlable"]
    publish_path = env["publish_path"]

    # Read existing mnemonic if encrypted
    _, mnemonic = _read_encryption_state(corpus_root, shape_name, content_path) if encrypted else (False, None)

    from cli.output import header, detail

    header("Deploying:", str(content_path.relative_to(corpus_root)))
    detail("Shape:", shape_name)
    detail("Env:", env_name)
    detail("Remote:", env["remote"])
    detail("URL:", base_url)
    detail("Encrypted:", "yes" if encrypted else "no")
    detail("Local-first:", "yes" if local_first else "no")
    detail("SW:", "yes" if service_worker else "no")
    detail("Crawlable:", crawlable)

    # Resolve chat binding when this is a grove target
    if shape_name == "grove":
        if not (content_path / "grove.yaml").is_file():
            raise SystemExit(f"grove target has no grove.yaml: {content_path}")
        grove = yaml.safe_load((content_path / "grove.yaml").read_text())
        binding = resolve_chat_binding(grove, env, env_name, corpus_root)
    else:
        binding = {"endpoint": None, "gate": None, "code": None, "feature_endpoints": {}}

    # Build — each shape's build() has its own positional signature.
    # Suppress build's own print output (access code etc.) — deploy controls output.
    import inspect
    import io
    import contextlib
    build_mod = _load_shape_build(corpus_root, shape_name)
    sig = inspect.signature(build_mod.build)
    params = list(sig.parameters.keys())

    build_kwargs = {"encrypted": encrypted, "mnemonic": mnemonic, "rotate": False}
    if "base_url" in params:
        build_kwargs["base_url"] = base_url
    if "service_worker" in params:
        build_kwargs["service_worker"] = service_worker
    if "local_first" in params:
        build_kwargs["local_first"] = local_first
    if "on_clear" in params:
        build_kwargs["on_clear"] = on_clear
    if "crawlable" in params:
        build_kwargs["crawlable"] = crawlable
    if "feature_endpoints" in params and binding["feature_endpoints"]:
        build_kwargs["feature_endpoints"] = binding["feature_endpoints"]
    if "chat_config" in params and binding["endpoint"]:
        build_kwargs["chat_config"] = {"endpoint": binding["endpoint"],
                                       "gate": binding["gate"]}

    with contextlib.redirect_stdout(io.StringIO()):
        if "instance_name" in params:
            build_dir, mnemonic_out = build_mod.build(content_path, shape_name, corpus_root, **build_kwargs)
        else:
            build_dir, mnemonic_out = build_mod.build(content_path, corpus_root, **build_kwargs)

    if mnemonic_out:
        mnemonic = mnemonic_out
        _save_encryption_state(corpus_root, content_path, mnemonic)

    # Probe the check route from the grove origin before publishing — confirms CORS
    # + the gate accepts a real code (the deploy holds it; it is never baked in).
    if binding["gate"]:
        probe_chat(binding["gate"]["check"], origin_of(base_url), binding["code"])

    # Resolve credentials and build adapter config
    credentials = resolve_credentials(remote, env["remote"], corpus_root)
    config = _build_config_for_adapter(remote, credentials, env)

    # Deploy
    config.update(caps)
    outcome = adapter_mod.deploy(build_dir, config, publish_path, force=force, spa=encrypted)
    _report_outcome(adapter_mod, outcome, mnemonic=mnemonic if encrypted else None)


def _report_outcome(adapter_mod, outcome, *, mnemonic) -> None:
    """Print what the adapter says happened. Staged is not live: no done mark
    (exit code stays 0 — staging is a legitimate step, not a failure)."""
    from cli.output import detail, output_file, warning, done
    if not isinstance(outcome, (Live, Staged)):
        raise SystemExit(f"adapter {adapter_mod.__name__} deploy() returned {outcome!r} — "
                         f"it must return Live or Staged (shapes/shared/adapters/outcome.py)")
    if isinstance(outcome, Staged):
        warning(f"STAGED (not live): {outcome.reason}")
    output_file(outcome.url)
    if mnemonic:
        detail("Access:", mnemonic)
        token = base64.urlsafe_b64encode(mnemonic.encode()).rstrip(b'=').decode()
        output_file(f"{outcome.url}#access={token}")
    if isinstance(outcome, Live):
        done()


def _note_aliased_env(corpus_root: Path, svc_ref, env_name: str) -> None:
    """A provider env that is the same config as another env (a YAML alias, e.g.
    notes `hetzner-staging: *prod`) deploys and syncs that other env's box —
    say so before it happens."""
    target, env, _ = _resolve_spine(corpus_root, svc_ref, env_name)
    same = [name for name, other in target["environments"].items()
            if name != env_name and other == env]
    if same:
        print(f"{svc_ref} {env_name} is the same box config as {', '.join(same)} "
              f"({env['domain']}) — this deploys and syncs it")


def run(corpus_root: Path, _instance, args: list) -> None:
    """Entry point for mo deploy.

    Usage: mo deploy <target> <env> [--force] [--dry-run] [--no-chain] [--take-dns]
    """
    force = dry_run = no_chain = take_dns = False
    positional = []
    for a in args:
        if a == "--force":
            force = True
        elif a == "--dry-run":
            dry_run = True
        elif a == "--no-chain":
            no_chain = True
        elif a == "--take-dns":
            take_dns = True
        elif a.startswith("--"):
            raise SystemExit(f"unknown flag {a} (known: --force --dry-run --no-chain --take-dns)")
        else:
            positional.append(a)

    if len(positional) < 2:
        print("Usage: mo deploy <target> <env> [--force] [--dry-run] [--no-chain] [--take-dns]")
        sys.exit(1)

    path_arg, env_name = positional[0], positional[1]

    # Validate self's flags against self's adapter before any provider converges.
    self_target, self_env, self_remote = _resolve_spine(
        corpus_root, _ref_of(corpus_root, path_arg), env_name)
    if _discriminator(self_target) == "stack":
        _refuse_take_dns_on_stack(take_dns)
    else:
        _check_capabilities(_load_adapter(corpus_root, self_remote["adapter"]),
                            self_env["remote"], take_dns=take_dns)

    # Read the target's declared service dependencies (the chain) — conditional.
    services = dict(self_env.get("services") or {}) if not no_chain else {}

    for svc_ref in services.values():                          # providers first
        _note_aliased_env(corpus_root, svc_ref, env_name)
        _deploy_one(corpus_root, svc_ref, env_name, force, dry_run, take_dns=False)
    _deploy_one(corpus_root, _ref_of(corpus_root, path_arg), env_name, force, dry_run,
                take_dns=take_dns)                             # self
    for svc_ref in services.values():                          # corpora last
        bt, be, _ = _resolve_spine(corpus_root, svc_ref, env_name)
        if "stack" in bt and be.get("corpus"):
            if dry_run:
                print(f"  would sync corpus: {svc_ref}")
            else:
                from cli.sync.corpus import sync
                from datetime import datetime
                sync.run(corpus_root, svc_ref, env_name,
                         now=datetime.now().strftime("%Y%m%d-%H%M%S"))
