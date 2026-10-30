"""mo sync init <folder> --remote <id> [--encryption age-ssh --recipients <key> ...]"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from cli.sync.config import (
    EncryptionConfig,
    SyncDeclaration,
    write_sync_declaration,
)
from cli.sync.errors import (
    ConfigValidationError,
    InvalidRecipientError,
    RemoteNotFoundError,
    SSHAccessError,
    SSHAgentUnavailableError,
)
from cli.sync.cli.resolve import (
    compute_declaration_path,
    find_infrastructure,
    resolve_infrastructure,
)


def _validate_ssh_pubkey(value: str) -> str:
    """Validate an SSH public key string. Returns the key. Raises InvalidRecipientError."""
    parts = value.strip().split()
    if len(parts) < 2:
        raise InvalidRecipientError(f"not a valid SSH public key: {value}")
    key_type = parts[0]
    if key_type != "ssh-ed25519":
        raise InvalidRecipientError(
            f"only Ed25519 keys are supported in v3, got: {key_type}"
        )
    return value.strip()


def _resolve_recipient(value: str) -> str:
    """Resolve a recipient value: if it's a .pub file path, read it. Then validate."""
    value = value.strip()
    candidate = Path(value).expanduser()
    if candidate.suffix == ".pub" and candidate.exists():
        value = candidate.read_text().strip().splitlines()[0].strip()
    return _validate_ssh_pubkey(value)


def _verify_ssh_access(repo_url: str) -> None:
    """Verify SSH access to the git host. Raises SSHAccessError on failure."""
    if not repo_url.startswith("git@"):
        raise SSHAccessError(f"cannot parse host from repo URL: {repo_url}")

    host = repo_url.split(":")[0].split("@")[1]
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", f"git@{host}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 255:
        raise SSHAccessError(
            f"SSH access failed for {host}: {result.stderr.strip()}"
        )


def _load_sync_remotes(infrastructure_path: Path) -> dict:
    """Load remotes.yaml and return only git_sync remotes."""
    from cli.infra.remotes import load_remotes
    all_remotes = load_remotes(infrastructure_path.parent)
    return {k: v for k, v in all_remotes.items() if v["adapter"] == "git_sync"}


def _get_agent_pubkeys() -> list[str]:
    """Get public keys from the SSH agent via ssh-add -L.

    Raises SSHAgentUnavailableError if the agent is not running.
    Returns empty list only if agent is running but has no keys.
    """
    result = subprocess.run(
        ["ssh-add", "-L"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 2:
        raise SSHAgentUnavailableError("SSH agent is not running")
    if result.returncode != 0 and "no identities" in result.stderr.lower():
        return []
    if result.returncode != 0:
        raise SSHAgentUnavailableError(f"ssh-add failed: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _check_agent_has_matching_key(recipients: list[str]) -> None:
    """Warn if no SSH agent key matches any recipient. Does not fail."""
    try:
        agent_keys = _get_agent_pubkeys()
    except SSHAgentUnavailableError:
        print("WARNING: SSH agent is not running. Decryption will fail on this device.")
        return

    if not agent_keys:
        print("WARNING: SSH agent has no keys loaded. Decryption will fail on this device.")
        return

    def _key_fingerprint(key: str) -> str:
        parts = key.split()
        return " ".join(parts[:2]) if len(parts) >= 2 else key

    agent_fps = {_key_fingerprint(k) for k in agent_keys}
    recipient_fps = {_key_fingerprint(r) for r in recipients}

    if not agent_fps & recipient_fps:
        print(
            "WARNING: SSH agent has no matching key for any declared recipient.\n"
            "  Decryption will fail on this device until a matching key is loaded.\n"
            f"  Agent keys: {len(agent_keys)}, Recipients: {len(recipients)}"
        )


def _git_init(folder_path: Path, remote_cfg: dict, remote_name: str = "origin") -> None:
    """Initialize git repo in folder, configure user and remote."""
    from cli.sync.git_sync import git_init, git_configure_user, git_add_remote

    git_init(folder_path)
    git_configure_user(folder_path, remote_cfg["git_user"], remote_cfg["git_email"])
    git_add_remote(folder_path, remote_name, remote_cfg["repo"])


def _notify_daemon() -> None:
    """Tell the daemon to rescan declarations. Prints result or warning."""
    import asyncio
    from cli.sync.client import SyncClient

    async def _rescan():
        client = SyncClient()
        await client.connect()
        try:
            await client.rescan()
        finally:
            await client.close()

    try:
        asyncio.run(_rescan())
        print("Daemon notified.")
    except ConnectionRefusedError:
        print("Daemon not running — start it with 'mo sync daemon start'.")
    except FileNotFoundError:
        pass  # no socket = no daemon running, not an error


def run_init(
    infrastructure_path: Path,
    folder_path: Path,
    remote_id: str,
    encryption: str,
    recipients: list[str],
) -> None:
    """Core init logic. All parameters required. Raises domain errors."""
    from cli.sync.git_sync import git_pull
    from cli.sync.errors import GitCommandError

    folder_path = folder_path.resolve()

    if not folder_path.exists():
        raise ConfigValidationError(f"folder does not exist: {folder_path}")

    decl_path = compute_declaration_path(infrastructure_path, folder_path)

    if decl_path.exists():
        raise ConfigValidationError(
            f"already configured: {decl_path}\n"
            f"  Use 'mo sync forget' first, or edit the file directly."
        )

    available = _load_sync_remotes(infrastructure_path)
    if remote_id not in available:
        available_str = ", ".join(sorted(available)) if available else "(none)"
        raise RemoteNotFoundError(
            f"unknown remote: {remote_id}. Available git_sync remotes: {available_str}"
        )

    remote_cfg = available[remote_id]

    if encryption not in ("none", "age-ssh"):
        raise ConfigValidationError(f"unknown encryption type: {encryption}")

    resolved_recipients: list[str] = []
    if encryption == "age-ssh":
        if not recipients:
            raise ConfigValidationError("--encryption age-ssh requires --recipients")
        for r in recipients:
            resolved_recipients.append(_resolve_recipient(r))

    _verify_ssh_access(remote_cfg["repo"])

    if encryption == "age-ssh":
        _check_agent_has_matching_key(resolved_recipients)

    target = os.path.relpath(folder_path.resolve(), decl_path.parent.resolve())

    decl = SyncDeclaration(
        version=1,
        target=target,
        remote=remote_id,
        encryption=EncryptionConfig(type=encryption, recipients=resolved_recipients),
    )
    write_sync_declaration(decl_path, decl)
    print(f"Wrote {decl_path}")

    _git_init(folder_path, remote_cfg)
    print(f"Initialized git in {folder_path}")

    gitignore = folder_path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            ".DS_Store\n*.swp\n*~\n.#*\nstate.sqlite\n__pycache__/\n.rendered/\n"
        )

    branch = remote_cfg["branch"]
    try:
        git_pull(folder_path, "origin", branch)
        print("Initial pull complete.")
    except GitCommandError as exc:
        stderr = exc.stderr.lower() if exc.stderr else ""
        if "couldn't find remote ref" in stderr or "no such ref" in stderr:
            print("Remote is empty — nothing to pull. Will push on first sync.")
        else:
            raise

    _notify_daemon()


def _parse_args(args: list) -> dict:
    """Parse CLI args into a dict."""
    result = {
        "folder": None,
        "infrastructure": None,
        "remote": None,
        "encryption": "none",
        "recipients": [],
    }

    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--infrastructure" and i + 1 < len(args):
            result["infrastructure"] = args[i + 1]
            i += 2
        elif args[i] == "--remote" and i + 1 < len(args):
            result["remote"] = args[i + 1]
            i += 2
        elif args[i] == "--encryption" and i + 1 < len(args):
            result["encryption"] = args[i + 1]
            i += 2
        elif args[i] == "--recipients" and i + 1 < len(args):
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                result["recipients"].append(args[i])
                i += 1
        else:
            positional.append(args[i])
            i += 1

    if positional:
        result["folder"] = positional[0]

    return result


USAGE = """\
Usage: mo sync init <folder> --remote <remote-id> [options]

Options:
  --remote <id>                Remote from infrastructure/remotes.yaml (required)
  --encryption <type>          none | age-ssh (default: none)
  --recipients <key> ...       SSH public keys or .pub file paths (required for age-ssh)
  --infrastructure <path>      Path to infrastructure/ (auto-detected if omitted)

Examples:
  mo sync init content --remote github/moui-sync-content
  mo sync init personal --remote codeberg/personal-sync --encryption age-ssh --recipients ~/.ssh/id_ed25519.pub"""


def run(corpus_root: Path, args: list):
    """CLI entry point. Parses args, catches domain errors, prints and exits."""
    from cli.sync.errors import MouiSyncError

    parsed = _parse_args(args)

    if not parsed["folder"]:
        print(USAGE)
        sys.exit(1)

    if not parsed["remote"]:
        print("--remote is required.\n")
        print(USAGE)
        sys.exit(1)

    folder_path = Path(parsed["folder"]).resolve()

    try:
        infrastructure_path = resolve_infrastructure(args)
    except MouiSyncError as exc:
        print(str(exc))
        sys.exit(1)

    try:
        run_init(
            infrastructure_path=infrastructure_path,
            folder_path=folder_path,
            remote_id=parsed["remote"],
            encryption=parsed["encryption"],
            recipients=parsed["recipients"],
        )
    except MouiSyncError as exc:
        print(str(exc))
        sys.exit(1)
