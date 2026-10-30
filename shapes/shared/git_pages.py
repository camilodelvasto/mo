"""Shared git-pages primitives — clone, merge/remove a subdirectory, push.

Mechanical git operations only. Platform-specific concerns (URL derivation,
CNAME file conventions, error subclasses) belong in the adapter that calls
these primitives.

Exposes exactly four functions:
    clone_and_merge(...)  — context manager for deploy
    clone_and_remove(...) — context manager for unpublish
    push(...)             — commit and push
    clone_and_reconcile(...)  — context manager for orphan manifest cleanup

Deploy writes are per-resource: each target deploy writes its own manifest and
does not touch others. Reconciliation is global: it scans all manifests in the
repo, compares against the declared set of publish_paths, and removes any
manifest (and its files) that no target claims. Reconciliation only runs when
the full target set for a remote is in scope — never from a single-target
deploy, since that lacks the visibility to safely identify orphans.
"""
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


class GitPagesError(Exception):
    pass


def _run_git(args: list[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, ["git"] + args,
            output=result.stdout, stderr=result.stderr,
        )
    return result


def _clone_or_init(repo_url: str, branch: str, work_dir: Path, git_user: str, git_email: str) -> None:
    """Clone the existing branch, or git init if the branch doesn't exist yet."""
    result = _run_git(
        ["clone", "--branch", branch, "--single-branch", "--depth", "1", repo_url, str(work_dir)],
        cwd=work_dir.parent,
    )
    if result.returncode != 0:
        work_dir.mkdir(parents=True, exist_ok=True)
        _run_git(["init"], cwd=work_dir)
        _run_git(["checkout", "-b", branch], cwd=work_dir)
        _run_git(["remote", "add", "origin", repo_url], cwd=work_dir)

    _run_git(["config", "user.name", git_user], cwd=work_dir)
    _run_git(["config", "user.email", git_email], cwd=work_dir)


_MANIFEST_PREFIX = ".deploy-manifest."


def _manifest_path(work_dir: Path, publish_path: str) -> Path:
    """Return the manifest file path for a given publish_path."""
    slug = publish_path.strip("/").replace("/", "--") or "root"
    return work_dir / f"{_MANIFEST_PREFIX}{slug}"


def _read_manifest(manifest: Path) -> set[str]:
    if manifest.exists():
        return set(manifest.read_text().splitlines())
    return set()


def _write_manifest(manifest: Path, entries: set[str]) -> None:
    manifest.write_text("\n".join(sorted(entries)) + "\n")


def _other_manifests(work_dir: Path, own_manifest: Path) -> set[str]:
    """Collect all entries owned by other deploys."""
    owned = set()
    for m in work_dir.glob(f"{_MANIFEST_PREFIX}*"):
        if m != own_manifest:
            owned |= _read_manifest(m)
    return owned


def _merge_into_subdirectory(dist_path: Path, work_dir: Path, publish_path: str) -> None:
    """Merge dist/ into publish_path within work_dir.

    Subdirectory deploys replace only their own directory. Root deploys track
    ownership via manifest files so they don't wipe subdirectories owned by
    other deploys.
    """
    target_dir = work_dir / publish_path.lstrip("/")
    if target_dir == work_dir:
        manifest = _manifest_path(work_dir, publish_path)
        old_entries = _read_manifest(manifest)
        protected = _other_manifests(work_dir, manifest)

        # Remove old root entries that aren't protected by other deploys
        for name in old_entries - protected:
            path = work_dir / name
            if not path.exists():
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

        # Copy new content
        new_entries = set()
        for item in dist_path.iterdir():
            if item.name.startswith(_MANIFEST_PREFIX):
                continue
            dst = work_dir / item.name
            if item.name in protected:
                # Don't overwrite directories owned by other deploys
                continue
            new_entries.add(item.name)
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            if item.is_dir():
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)

        _write_manifest(manifest, new_entries)
    else:
        manifest = _manifest_path(work_dir, publish_path)
        top_entry = publish_path.lstrip("/").split("/")[0]
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(dist_path, target_dir)
        _write_manifest(manifest, {top_entry})


def _remove_subdirectory(work_dir: Path, publish_path: str) -> None:
    """Remove publish_path from work_dir and clean up its manifest."""
    manifest = _manifest_path(work_dir, publish_path)
    target_dir = work_dir / publish_path.lstrip("/")
    if target_dir == work_dir:
        entries = _read_manifest(manifest)
        for name in entries:
            path = work_dir / name
            if not path.exists():
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    elif target_dir.exists():
        shutil.rmtree(target_dir)
    if manifest.exists():
        manifest.unlink()


@contextmanager
def clone_and_merge(
    dist_path: Path,
    repo_url: str,
    branch: str,
    publish_path: str,
    git_user: str,
    git_email: str,
    *,
    extra_root_files: dict[str, str] | None = None,
):
    """Clone the pages branch, merge dist_path into publish_path, write extras.

    Yields work_dir ready for push. Cleans up the temp clone on exit.

    Args:
        dist_path: directory of built static files to deploy
        repo_url: git remote URL
        branch: branch name to clone (required — no default)
        publish_path: subdirectory path on the pages branch (e.g. "/grove/blog")
        git_user, git_email: commit identity
        extra_root_files: {filename: content} to write at repo root
            (e.g. {".nojekyll": ""} for GitHub Pages, {".domains": "x.com\n"} for Codeberg)
    """
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp) / "pages"
        _clone_or_init(repo_url, branch, work_dir, git_user, git_email)

        _merge_into_subdirectory(dist_path, work_dir, publish_path)

        if extra_root_files:
            for name, content in extra_root_files.items():
                (work_dir / name).write_text(content)

        yield work_dir


@contextmanager
def clone_and_remove(
    repo_url: str,
    branch: str,
    publish_path: str,
    git_user: str,
    git_email: str,
):
    """Clone the pages branch, remove publish_path subdirectory.

    Yields work_dir ready for push. Cleans up the temp clone on exit.
    """
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp) / "pages"
        _clone_or_init(repo_url, branch, work_dir, git_user, git_email)
        _remove_subdirectory(work_dir, publish_path)
        yield work_dir


def push(work_dir: Path, branch: str, message: str, repo_url: str, *, force: bool = True) -> None:
    """Commit and push to branch on origin. Raise GitPagesError on failure."""
    _run_git(["add", "."], cwd=work_dir)
    _run_git(["commit", "-m", message, "--allow-empty"], cwd=work_dir)

    push_args = ["push"]
    if force:
        push_args.append("--force")
    push_args.extend(["origin", f"HEAD:{branch}"])

    result = _run_git(push_args, cwd=work_dir)
    if result.returncode != 0:
        raise GitPagesError(
            f"Deploy failed: git push to {repo_url} rejected.\n"
            f"stdout: {result.stdout.strip()}\n"
            f"stderr: {result.stderr.strip()}\n"
            f"\nIf credentials are not configured:\n"
            f"  git config --global credential.helper store\n"
            f"  git push {repo_url}  (enter credentials once)"
        )


def _manifest_to_publish_path(manifest_name: str) -> str:
    """Convert a manifest filename back to its publish_path.

    .deploy-manifest.root → /
    .deploy-manifest.school → /school
    .deploy-manifest.decks--pitch → /decks/pitch
    """
    slug = manifest_name[len(_MANIFEST_PREFIX):]
    if slug == "root":
        return "/"
    return "/" + slug.replace("--", "/")


def find_orphan_manifests(work_dir: Path, declared_paths: set[str]) -> list[tuple[str, str]]:
    """Compare manifests in repo against declared publish_paths.

    Returns list of (manifest_filename, publish_path) for manifests that are
    not claimed by any declared target.
    """
    orphans = []
    for manifest in work_dir.glob(f"{_MANIFEST_PREFIX}*"):
        publish_path = _manifest_to_publish_path(manifest.name)
        if publish_path not in declared_paths:
            orphans.append((manifest.name, publish_path))
    return orphans


def _remove_orphan(work_dir: Path, manifest_name: str) -> None:
    """Remove an orphan manifest and the files it owns."""
    manifest = work_dir / manifest_name
    entries = _read_manifest(manifest)
    for name in entries:
        path = work_dir / name
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    manifest.unlink()


@contextmanager
def clone_and_reconcile(
    repo_url: str,
    branch: str,
    declared_paths: set[str],
    git_user: str,
    git_email: str,
):
    """Clone the pages branch, identify and remove orphan manifests.

    Compares manifests in the repo against the declared set of publish_paths.
    Any manifest not in the declared set is stale — its files and manifest are
    removed. Yields (work_dir, orphans) where orphans is the list of removed
    paths. Caller is responsible for pushing.
    """
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp) / "pages"
        _clone_or_init(repo_url, branch, work_dir, git_user, git_email)
        orphans = find_orphan_manifests(work_dir, declared_paths)
        for manifest_name, _publish_path in orphans:
            _remove_orphan(work_dir, manifest_name)
        yield work_dir, orphans
