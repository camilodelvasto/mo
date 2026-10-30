"""Load and query infrastructure/remotes.yaml."""
from pathlib import Path

import yaml


class RemotesError(Exception):
    pass


def load_remotes(corpus_root: Path) -> dict:
    """Load remotes.yaml, return the remotes dict. Raises on missing or empty."""
    remotes_path = corpus_root / "infrastructure" / "remotes.yaml"
    if not remotes_path.exists():
        raise RemotesError(
            f"No remotes.yaml found at {remotes_path}\n"
            f"  Create infrastructure/remotes.yaml with your deployment remotes."
        )
    raw = yaml.safe_load(remotes_path.read_text())
    remotes = raw.get("remotes", {})
    if not remotes:
        raise RemotesError(
            f"{remotes_path}: no remotes defined.\n"
            f"  Add at least one remote under the 'remotes:' key."
        )
    return remotes


def get_remote(remotes: dict, remote_id: str) -> dict:
    """Look up a remote by id. Raises RemotesError with known remotes listed."""
    if remote_id not in remotes:
        known = ", ".join(sorted(remotes.keys()))
        raise RemotesError(
            f'Unknown remote "{remote_id}"\n'
            f"  Known remotes: {known}"
        )
    return remotes[remote_id]
