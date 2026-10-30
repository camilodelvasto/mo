"""Grove collection loader."""
import yaml
from pathlib import Path


class CollectionError(Exception):
    """Raised on invalid collection."""


def load_collections(collections_dir):
    """Load all .yaml files from collections/. Returns list of collection dicts."""
    collections_dir = Path(collections_dir)
    if not collections_dir.exists():
        return []
    collections = []
    for f in sorted(collections_dir.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not data.get("id"):
            raise CollectionError(f"{f}: missing 'id'")
        if not data.get("title"):
            raise CollectionError(f"{f}: missing 'title'")
        if not data.get("posts"):
            raise CollectionError(f"{f}: missing 'posts'")
        data["_source_path"] = str(f)
        collections.append(data)
    return collections


def resolve_collection_posts(collection, posts_by_path):
    """Resolve post references in a collection to actual post dicts.
    Throws CollectionError if a referenced path is not found."""
    resolved = []
    for ref in collection["posts"]:
        if ref not in posts_by_path:
            raise CollectionError(
                f"Collection '{collection['id']}': post '{ref}' not found. "
                f"Available: {', '.join(sorted(posts_by_path.keys()))}"
            )
        resolved.append(posts_by_path[ref])
    return resolved
