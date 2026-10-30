"""Credential resolution for remotes.

Resolves credentials from the source declared in the remote's `credential:` key.
Four source types: ssh-agent, file path, env var, keychain.
Implicit fallback when credential key is absent.
"""
import os
from pathlib import Path

import yaml


class CredentialError(Exception):
    pass


def resolve_credentials(remote: dict, remote_id: str, corpus_root: Path) -> dict:
    """Resolve credentials for a remote. Returns dict of credential values.

    Raises CredentialError with named sources tried on failure.
    """
    credential = remote.get("credential")

    if credential is None:
        return _resolve_implicit(remote_id, corpus_root)

    if credential == "ssh-agent":
        return {}

    if isinstance(credential, str) and credential.startswith("secrets/"):
        return _resolve_file(credential, remote_id, corpus_root)

    if isinstance(credential, dict):
        cred_type = credential.get("type")
        if cred_type == "env":
            return _resolve_env(credential, remote_id)
        if cred_type == "keychain":
            return _resolve_keychain(credential, remote_id)
        raise CredentialError(
            f'Unknown credential type "{cred_type}" for remote "{remote_id}"'
        )

    raise CredentialError(
        f'Unrecognized credential value for remote "{remote_id}": {credential}'
    )


def _resolve_file(path_str: str, remote_id: str, corpus_root: Path) -> dict:
    file_path = corpus_root / path_str
    if not file_path.exists():
        raise CredentialError(
            f'Cannot deploy — no credentials for remote "{remote_id}"\n\n'
            f"  Tried:\n"
            f"    credential key     {path_str} (declared, file not found)\n\n"
            f"  Run: mo remote setup {remote_id}"
        )
    return yaml.safe_load(file_path.read_text()) or {}


def _resolve_env(credential: dict, remote_id: str) -> dict:
    var = credential["var"]
    value = os.environ.get(var)
    if value is None:
        raise CredentialError(
            f'Cannot deploy — no credentials for remote "{remote_id}"\n\n'
            f"  Tried:\n"
            f"    env var            {var} (not set)\n\n"
            f"  Set {var} in your environment or CI secrets."
        )
    return {"token": value}


def _resolve_keychain(credential: dict, remote_id: str) -> dict:
    raise CredentialError(
        f'Keychain credential resolution not yet implemented for remote "{remote_id}"'
    )


def _resolve_implicit(remote_id: str, corpus_root: Path) -> dict:
    """Implicit resolution: try file, then env var."""
    parts = remote_id.split("/", 1)
    if len(parts) != 2:
        raise CredentialError(
            f'Remote id "{remote_id}" does not follow provider/instance convention'
        )
    provider, instance = parts

    file_path = corpus_root / "secrets" / provider / f"{instance}.yaml"
    if file_path.exists():
        return yaml.safe_load(file_path.read_text()) or {}

    env_var = f"MOUI_{provider.upper()}_{instance.upper().replace('-', '_')}_TOKEN"
    env_value = os.environ.get(env_var)
    if env_value is not None:
        return {"token": env_value}

    raise CredentialError(
        f'Cannot deploy — no credentials resolved for remote "{remote_id}"\n\n'
        f"  Tried:\n"
        f"    implicit fallback  secrets/{provider}/{instance}.yaml (file not found)\n"
        f"    implicit fallback  {env_var} (env var not set)\n\n"
        f"  Run: mo remote setup {remote_id}"
    )
