"""Codeberg Pages deploy adapter.

Owns Codeberg-specific concerns: URL derivation, `.domains` file for custom
domains, and its own error subclass. Uses git_pages for mechanical git work.

Custom domain setup (operator responsibility, outside this adapter):

  Branch requirement: content MUST be on the repo's default branch (typically
  `main`). Codeberg runs both git-pages (new) and pages-server (legacy) behind
  the same infrastructure. Custom domain routing and TLS cert provisioning only
  work when content is on the default branch. Pushing to a non-default branch
  (e.g. `pages`) serves fine under *.codeberg.page but custom domains will fail
  with TLS internal errors. Set `branch: main` in the remote config.

  The adapter writes the `.domains` file automatically when it detects a
  non-default domain. First line is canonical; others 307-redirect to it.
  The operator must configure DNS separately.

  DNS target format: [[branch.]repo.]{owner}.codeberg.page
    - If repo is named "pages" (org/user site), target is just {owner}.codeberg.page
    - Otherwise, target is {repo}.{owner}.codeberg.page

  Subdomains (e.g. www.moui.io) — CNAME only, no TXT needed:
    www.moui.io  CNAME  {owner}.codeberg.page
    Codeberg resolves the repo from the CNAME target. A TXT record cannot
    coexist with CNAME on the same name (DNS standard).

  Apex domains (e.g. moui.io) — CNAME not allowed on apex, use A/AAAA + TXT:
    moui.io  A      217.197.84.141
    moui.io  AAAA   2a0a:4580:103f:c0de::2
    moui.io  TXT    {owner}.codeberg.page
    The TXT record tells Codeberg which repo serves the domain. Without it,
    Codeberg cannot match the domain to a repo and will not provision a TLS
    certificate. The A/AAAA IPs are Codeberg's Pages servers.

  Cert provisioning happens automatically via Let's Encrypt (through Caddy's
  on-demand TLS) after DNS propagates. No manual cert setup required.
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


class CodebergError(GitPagesError):
    pass


# capabilities the deploy rail injects into config — none
REQUIRES = ()


REQUIRED_FIELDS = ("repo_url", "branch", "git_user", "git_email")

_CODEBERG_PATTERN = re.compile(r'^[^.]+\.codeberg\.page$')


def _validate_config(config: dict) -> None:
    missing = [f for f in REQUIRED_FIELDS if not config.get(f)]
    if missing:
        raise CodebergError(
            f"Codeberg Pages config missing required fields: {', '.join(missing)}"
        )


def _custom_domain(config: dict) -> str | None:
    """Return domain if it doesn't match the default Codeberg Pages pattern, else None."""
    domain = config.get("domain")
    if not domain:
        return None
    if _CODEBERG_PATTERN.match(domain):
        return None
    return domain


def _validate_custom_domain(config: dict, publish_path: str) -> None:
    """Warn if a non-root deploy has aliases that won't be written.

    Subdirectory deploys to a repo with a custom domain are valid — the deck
    lives at www.moui.io/decks/pitch while the root owns the .domains file.
    But aliases only make sense at root (where .domains is written), so flag
    a likely misconfiguration.
    """
    if publish_path == "/":
        return
    if config.get("aliases"):
        raise CodebergError(
            f"aliases are only written to .domains at publish_path: /, got '{publish_path}'"
        )


def _extra_root_files(config: dict) -> dict[str, str]:
    """Codeberg custom domains live in a `.domains` file at repo root.

    First line is canonical domain, others redirect to it. Only custom domains
    go here — the codeberg.page origin is resolved via DNS (CNAME or TXT), not
    via the .domains file.
    """
    domain = _custom_domain(config)
    if domain:
        domains = [domain] + config.get("aliases", [])
        return {".domains": "\n".join(domains) + "\n"}
    return {}


def _derive_url(config: dict, publish_path: str) -> str:
    """Derive the public URL for a Codeberg Pages deploy."""
    domain = _custom_domain(config)
    if domain:
        return f"https://{domain}{publish_path}"
    repo_url = config["repo_url"]
    match = re.search(r'codeberg\.org[/:]([^/]+)/', repo_url)
    if not match:
        raise CodebergError(
            f"Cannot derive Codeberg Pages URL from repo_url: {repo_url}"
        )
    return f"https://{match.group(1)}.codeberg.page{publish_path}"


def deploy(dist_path: Path, config: dict, publish_path: str, *, force: bool = True, spa: bool = False) -> Live:
    _validate_config(config)
    _validate_custom_domain(config, publish_path)
    if spa:
        redirects = dist_path / "_redirects"
        existing = redirects.read_text() if redirects.exists() else ""
        redirects.write_text(existing + "/* /index.html 200\n")
    # Only root deploys write .domains — subdirectory deploys must not overwrite
    # the root's .domains file (which may contain aliases they don't know about).
    extra = _extra_root_files(config) if publish_path == "/" else {}
    with clone_and_merge(
        dist_path,
        config["repo_url"],
        config["branch"],
        publish_path,
        config["git_user"],
        config["git_email"],
        extra_root_files=extra,
    ) as work_dir:
        try:
            push(work_dir, config["branch"], f"deploy: {publish_path}",
                 config["repo_url"], force=force)
        except GitPagesError as e:
            raise CodebergError(str(e)) from e
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
            raise CodebergError(str(e)) from e
