"""Handler for: mo remote list | verify <id> | setup [<id>|--all]

Manages infrastructure remotes and their credentials.
"""
import sys
from pathlib import Path

from cli.infra.remotes import load_remotes, RemotesError
from cli.infra.resolver import resolve_credentials, CredentialError


def _credential_status(remote: dict, remote_id: str, corpus_root: Path) -> tuple:
    """Return (source_description, status) for a remote's credential."""
    credential = remote.get("credential", "implicit")

    if isinstance(credential, str):
        source = credential
    elif isinstance(credential, dict):
        source = f"{credential.get('type')}:{credential.get('var', credential.get('service', ''))}"
    else:
        source = "unknown"

    try:
        resolve_credentials(remote, remote_id, corpus_root)
        return source, "ok"
    except CredentialError:
        return source, "missing"


def _list_remotes(corpus_root: Path) -> None:
    remotes = load_remotes(corpus_root)
    print()
    for remote_id, remote in sorted(remotes.items()):
        source, status = _credential_status(remote, remote_id, corpus_root)
        mark = "\u2713" if status == "ok" else "\u2717"
        adapter = remote.get("adapter", "?")
        print(f"  {remote_id}")
        print(f"    Adapter:    {adapter}")
        print(f"    Credential: {source} ({mark} {status})")
        print()


def _verify_remote(corpus_root: Path, remote_id: str) -> None:
    remotes = load_remotes(corpus_root)
    if remote_id not in remotes:
        known = ", ".join(sorted(remotes.keys()))
        print(f'Unknown remote "{remote_id}". Known: {known}')
        sys.exit(1)

    remote = remotes[remote_id]
    try:
        creds = resolve_credentials(remote, remote_id, corpus_root)
        print(f"\n  {remote_id}: credentials resolved")
        print(f"    adapter: {remote.get('adapter')}")
        for k in creds:
            print(f"    {k}: {'*' * 8}")
        print()
    except CredentialError as e:
        print(f"\n  {e}\n")
        sys.exit(1)


def _setup_remote(corpus_root: Path, remote_id: str) -> None:
    # Check .gitignore
    gitignore = corpus_root / ".gitignore"
    if not gitignore.exists() or "secrets/" not in gitignore.read_text():
        print("Refusing: secrets/ is not in .gitignore")
        print("  Add 'secrets/' to .gitignore first.")
        sys.exit(1)

    remotes = load_remotes(corpus_root)
    if remote_id not in remotes:
        known = ", ".join(sorted(remotes.keys()))
        print(f'Unknown remote "{remote_id}". Known: {known}')
        sys.exit(1)

    remote = remotes[remote_id]
    credential = remote.get("credential")

    if credential == "ssh-agent":
        print(f"\n  {remote_id}: uses ssh-agent, no file needed.")
        print()
        return

    # Determine target file
    parts = remote_id.split("/", 1)
    if len(parts) != 2:
        print(f"Remote id must be provider/instance format: {remote_id}")
        sys.exit(1)

    provider, instance = parts
    secrets_path = corpus_root / "secrets" / provider / f"{instance}.yaml"

    if secrets_path.exists():
        print(f"\n  {remote_id}: credentials already exist at {secrets_path}")
        print()
        return

    if "adapter" not in remote:
        raise SystemExit(f"remote {remote_id} declares no adapter — "
                         f"setup prompts depend on it")
    adapter = remote["adapter"]

    print(f"\n  Setting up: {remote_id}")
    print(f"  Adapter: {adapter}")
    print(f"  Target file: {secrets_path}")
    print()

    # Interactive — adapter-specific prompts
    secrets_path.parent.mkdir(parents=True, exist_ok=True)

    if "pages" in adapter:
        token = input("  Token (for HTTPS push): ").strip()
        secrets_path.write_text(f"token: {token}\n")
    elif adapter == "hetzner":
        # A passphrase-protected key belongs in ssh-agent, not in a secrets file.
        ssh_key = input("  SSH key path (leave empty for default): ").strip()
        secrets_path.write_text(f"ssh_key: {ssh_key}\n" if ssh_key else "")
    elif adapter == "s3":
        access_key = input("  Access key ID: ").strip()
        secret_key = input("  Secret access key: ").strip()
        secrets_path.write_text(
            f"access_key_id: {access_key}\nsecret_access_key: {secret_key}\n"
        )
    else:
        token = input("  Token/key: ").strip()
        secrets_path.write_text(f"token: {token}\n")

    print(f"  Written to {secrets_path}")
    print()


def run(corpus_root: Path, args: list) -> None:
    if not args:
        print("Usage: mo remote list | verify <id> | setup [<id>|--all]")
        sys.exit(1)

    subcommand = args[0]
    sub_args = args[1:]

    if subcommand == "list":
        _list_remotes(corpus_root)
    elif subcommand == "verify":
        if not sub_args:
            print("Usage: mo remote verify <remote-id>")
            sys.exit(1)
        _verify_remote(corpus_root, sub_args[0])
    elif subcommand == "setup":
        if not sub_args:
            print("Usage: mo remote setup <remote-id> | --all")
            sys.exit(1)
        if sub_args[0] == "--all":
            remotes = load_remotes(corpus_root)
            for rid in sorted(remotes):
                _setup_remote(corpus_root, rid)
        else:
            _setup_remote(corpus_root, sub_args[0])
    else:
        print(f"Unknown subcommand: mo remote {subcommand}")
        sys.exit(1)
