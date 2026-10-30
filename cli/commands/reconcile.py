"""Handler for: mo reconcile <remote-id> [--dry-run]

Scans all infrastructure/targets/ for the given remote, builds the declared
set of publish_paths, clones the remote repo, and removes any deploy manifest
(and its owned files) not claimed by a current target.

This is the global cleanup operation. Per-target deploys write their own
manifest and never touch others. Reconciliation runs when the full target set
for a remote is in scope — it has the visibility to safely identify orphans.
"""
import importlib.util
import sys
from pathlib import Path

from cli.infra.remotes import load_remotes, get_remote
from cli.infra.targets import declared_paths_by_remote
from cli.infra.resolver import resolve_credentials

# Reconcile removes orphan manifests from a pages branch: git-pages remotes only.
GIT_PAGES_ADAPTERS = ("codeberg_pages", "github_pages")


def _load_git_pages(corpus_root: Path):
    shared_dir = corpus_root / "shapes" / "shared"
    spec = importlib.util.spec_from_file_location(
        "git_pages", shared_dir / "git_pages.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(corpus_root: Path, args: list) -> None:
    """Entry point for mo reconcile."""
    dry_run = "--dry-run" in args
    positional = [a for a in args if not a.startswith("--")]

    if not positional:
        print("Usage: mo reconcile <remote-id> [--dry-run]")
        sys.exit(1)

    remote_id = positional[0]

    from cli.output import header, detail, done

    remotes = load_remotes(corpus_root)
    remote = get_remote(remotes, remote_id)
    if "adapter" not in remote:
        raise SystemExit(f"mo reconcile: remote {remote_id} declares no adapter — a stack "
                         f"remote is converged, not copied to; nothing to reconcile")
    if remote["adapter"] not in GIT_PAGES_ADAPTERS:
        raise SystemExit(f"mo reconcile: remote {remote_id} uses adapter {remote['adapter']}; "
                         f"reconcile works on git-pages remotes only "
                         f"({', '.join(GIT_PAGES_ADAPTERS)})")

    all_paths = declared_paths_by_remote(corpus_root)
    declared = all_paths.get(remote_id, set())

    header("Reconciling:", remote_id)
    detail("Declared paths:", ", ".join(sorted(declared)) if declared else "(none)")

    git_pages = _load_git_pages(corpus_root)

    repo_url = remote["repo"]
    branch = remote["branch"]
    credentials = resolve_credentials(remote, remote_id, corpus_root)
    git_user = remote["git_user"]
    git_email = remote["git_email"]

    with git_pages.clone_and_reconcile(
        repo_url, branch, declared, git_user, git_email
    ) as (work_dir, orphans):
        if not orphans:
            detail("Status:", "no orphan manifests found")
            done()
            return

        for manifest_name, publish_path in orphans:
            detail("Orphan:", f"{publish_path} ({manifest_name})")

        if dry_run:
            detail("Mode:", "dry-run — no changes pushed")
            done()
            return

        try:
            git_pages.push(
                work_dir, branch, "reconcile: remove orphan manifests",
                repo_url, force=True
            )
        except git_pages.GitPagesError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        detail("Removed:", f"{len(orphans)} orphan(s)")

    done()
