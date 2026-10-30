"""Incremental build — content hash diffing."""
import hashlib
import json
from pathlib import Path


def compute_hashes(directory: Path) -> dict[str, str]:
    """Compute SHA-256 hashes for all files in directory."""
    directory = Path(directory)
    hashes = {}
    for f in sorted(directory.rglob("*")):
        if f.is_file():
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            rel = str(f.relative_to(directory))
            hashes[rel] = digest
    return hashes


def diff_hashes(old: dict[str, str], new: dict[str, str]) -> set[str]:
    """Compare two hash manifests. Returns set of changed/added/deleted paths."""
    changed = set()
    for path, hash_val in new.items():
        if path not in old or old[path] != hash_val:
            changed.add(path)
    for path in old:
        if path not in new:
            changed.add(path)
    return changed


def save_manifest(hashes: dict[str, str], manifest_path: Path) -> None:
    """Save hash manifest to disk."""
    Path(manifest_path).write_text(json.dumps(hashes, sort_keys=True, indent=2), encoding="utf-8")


def load_manifest(manifest_path: Path) -> dict[str, str]:
    """Load hash manifest. Returns empty dict if not found."""
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))
