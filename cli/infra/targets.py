"""Load and validate infrastructure/targets/ files.

Target files mirror content/ structurally:
  content/moui/website/en/       → infrastructure/targets/moui/website/en.yaml
  content/moui/decks/pitch.yaml  → infrastructure/targets/moui/decks/pitch.yaml
"""
from pathlib import Path

import yaml


class TargetError(Exception):
    pass


def _target_path_for_content(content_path: Path, corpus_root: Path) -> Path:
    """Derive target file path from content path."""
    rel = content_path.relative_to(corpus_root / "content")
    if content_path.is_dir():
        return corpus_root / "infrastructure" / "targets" / rel.with_suffix(".yaml")
    else:
        return corpus_root / "infrastructure" / "targets" / rel


def load_target(ref, corpus_root: Path) -> dict:
    """Load the target file for a content path or a direct target ref.

    Two explicit dispatch cases — no fallback:

    1. Content path (Path object or str starting with "content/"):
       Derives target path via _target_path_for_content.
       Example: content/moui/website/en → infrastructure/targets/moui/website/en.yaml

    2. Direct target ref (str NOT starting with "content/"):
       Resolves directly to infrastructure/targets/<ref>.yaml.
       Example: "clients/acme/notes" → infrastructure/targets/clients/acme/notes.yaml
    """
    ref_str = str(ref)

    # Explicit dispatch: Path objects or refs under content/ → content-path resolution
    if isinstance(ref, Path) or ref_str.startswith("content/"):
        p = ref if isinstance(ref, Path) else Path(ref_str)
        if not p.is_absolute():
            p = corpus_root / p          # a relative content ref (e.g. a YAML services.chat
                                         # string, or `mo sync corpus content/…`) resolves
                                         # against the corpus root, same as the CLI's resolved path
        target_path = _target_path_for_content(p, corpus_root)
    else:
        # Direct target ref — not content-derived
        target_path = corpus_root / "infrastructure" / "targets" / f"{ref_str}.yaml"

    if not target_path.exists():
        raise TargetError(
            f"No target file found at {target_path}\n"
            f"  Create it to define deployment environments for this content."
        )
    raw = yaml.safe_load(target_path.read_text())
    if not isinstance(raw, dict) or "environments" not in raw:
        raise TargetError(
            f"{target_path}: missing 'environments' key"
        )
    return raw


def get_environment(target: dict, env_name: str) -> dict:
    """Get a named environment from a target. Raises TargetError if not found."""
    envs = target.get("environments", {})
    if env_name not in envs:
        available = ", ".join(sorted(envs.keys()))
        raise TargetError(
            f'Environment "{env_name}" not found.\n'
            f"  Available: {available}"
        )
    return envs[env_name]


def derive_base_url(env: dict) -> str:
    """Compute base_url from domain + base_path. Never stored — always derived."""
    domain = env["domain"]
    base_path = env["base_path"]
    return f"https://{domain}{base_path}"


def validate_remote_refs(target: dict, known_remotes: dict) -> None:
    """Validate that all remote references in environments exist in remotes.yaml."""
    for env_name, env in target.get("environments", {}).items():
        remote_id = env.get("remote")
        if remote_id and remote_id not in known_remotes:
            known = ", ".join(sorted(known_remotes.keys()))
            raise TargetError(
                f'Environment "{env_name}" references unknown remote "{remote_id}"\n'
                f"  Known remotes: {known}"
            )


def _declared_envs(corpus_root: Path):
    """Yield (target_file, env) for every environment of every target file.
    Reconciliation and the DNS guard both need complete visibility, so a
    malformed file throws."""
    targets_dir = corpus_root / "infrastructure" / "targets"
    if not targets_dir.exists():
        return
    for target_file in targets_dir.rglob("*.yaml"):
        raw = yaml.safe_load(target_file.read_text())
        if not isinstance(raw, dict) or "environments" not in raw:
            raise TargetError(
                f"Malformed target file: {target_file}\n"
                f"  Deploy and reconcile need complete visibility into all targets.\n"
                f"  Fix or remove this file."
            )
        for env in raw["environments"].values():
            yield target_file, env


def declared_paths_by_remote(corpus_root: Path) -> dict[str, set[str]]:
    """Scan all targets and return {remote_id: {publish_path, ...}}.

    This is the declared set of publish_paths per remote — the source of truth
    for what should exist. Any manifest in the remote repo not in this set is
    stale and should be removed by reconciliation.
    """
    result: dict[str, set[str]] = {}
    for _, env in _declared_envs(corpus_root):
        remote_id = env.get("remote")
        publish_path = env.get("publish_path")
        if remote_id and publish_path:
            result.setdefault(remote_id, set()).add(publish_path)
    return result


def declared_mounts(corpus_root: Path, domain: str) -> dict[str, list[tuple[str, str]]]:
    """{publish_path: [(remote_id, target_file), ...]} for every environment on ANY
    remote that declares this domain — what a deploy must account for before it
    moves the domain's DNS. target_file is relative to corpus_root; paths are
    spelled as declared."""
    mounts: dict[str, list[tuple[str, str]]] = {}
    for target_file, env in _declared_envs(corpus_root):
        if env.get("domain") != domain:
            continue
        if not env.get("publish_path") or not env.get("remote"):
            raise TargetError(f"{target_file}: an environment for {domain} "
                              f"declares no publish_path or no remote")
        mounts.setdefault(env["publish_path"], []).append(
            (env["remote"], target_file.relative_to(corpus_root).as_posix()))
    return {p: sorted(decls) for p, decls in mounts.items()}
