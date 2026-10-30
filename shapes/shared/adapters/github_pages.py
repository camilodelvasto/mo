"""GitHub Pages deploy adapter.

Owns GitHub-specific concerns: URL derivation, `.nojekyll` (disable Jekyll)
and `CNAME` (custom domain) root files, and its own error subclass. Uses
git_pages for mechanical git work.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from git_pages import (  # noqa: E402
    clone_and_merge,
    clone_and_remove,
    push,
    GitPagesError,
)
from shapes.shared.adapters.outcome import Live  # noqa: E402


class GitHubPagesError(GitPagesError):
    pass


# capabilities the deploy rail injects into config — none
REQUIRES = ()


REQUIRED_FIELDS = ("repo_url", "branch", "git_user", "git_email")

_GITHUB_PATTERN = re.compile(r'^[^.]+\.github\.io$')


def _validate_config(config: dict) -> None:
    missing = [f for f in REQUIRED_FIELDS if not config.get(f)]
    if missing:
        raise GitHubPagesError(
            f"GitHub Pages config missing required fields: {', '.join(missing)}"
        )


def _custom_domain(config: dict) -> str | None:
    """Return domain if it doesn't match the default GitHub Pages pattern, else None."""
    domain = config.get("domain")
    if not domain:
        return None
    if _GITHUB_PATTERN.match(domain):
        return None
    return domain


def _validate_custom_domain(config: dict, publish_path: str) -> None:
    """Warn if a non-root deploy has aliases that won't be written.

    Subdirectory deploys to a repo with a custom domain are valid — the CNAME
    file is only written at root. Aliases only make sense at root, so flag
    a likely misconfiguration.
    """
    if publish_path == "/":
        return
    if config.get("aliases"):
        raise GitHubPagesError(
            f"aliases are only written to CNAME at publish_path: /, got '{publish_path}'"
        )


def _extra_root_files(config: dict) -> dict[str, str]:
    """.nojekyll always; CNAME when a custom domain is detected."""
    files = {".nojekyll": ""}
    domain = _custom_domain(config)
    if domain:
        domains = [domain] + config.get("aliases", [])
        files["CNAME"] = "\n".join(domains) + "\n"
    return files


def _derive_url(config: dict, publish_path: str) -> str:
    """Derive the public URL for a GitHub Pages deploy."""
    domain = _custom_domain(config)
    if domain:
        return f"https://{domain}{publish_path}"
    repo_url = config["repo_url"]
    match = re.search(r'github\.com[/:]([^/]+)/([^/.]+)', repo_url)
    if not match:
        raise GitHubPagesError(
            f"Cannot derive GitHub Pages URL from repo_url: {repo_url}"
        )
    return f"https://{match.group(1)}.github.io/{match.group(2)}{publish_path}"


def deploy(dist_path: Path, config: dict, publish_path: str, *, force: bool = True, spa: bool = False) -> Live:
    _validate_config(config)
    _validate_custom_domain(config, publish_path)
    if spa:
        redirects = dist_path / "_redirects"
        existing = redirects.read_text() if redirects.exists() else ""
        redirects.write_text(existing + "/* /index.html 200\n")
    with clone_and_merge(
        dist_path,
        config["repo_url"],
        config["branch"],
        publish_path,
        config["git_user"],
        config["git_email"],
        extra_root_files=_extra_root_files(config),
    ) as work_dir:
        try:
            push(work_dir, config["branch"], f"deploy: {publish_path}",
                 config["repo_url"], force=force)
        except GitPagesError as e:
            raise GitHubPagesError(str(e)) from e
    return Live(_derive_url(config, publish_path))


def unpublish(config: dict, publish_path: str, *, force: bool = True) -> None:
    _validate_config(config)
    with clone_and_remove(
        config["repo_url"],
        config["branch"],
        publish_path,
        config["git_user"],
        config["git_email"],
    ) as work_dir:
        try:
            push(work_dir, config["branch"], f"unpublish: {publish_path}",
                 config["repo_url"], force=force)
        except GitPagesError as e:
            raise GitHubPagesError(str(e)) from e
