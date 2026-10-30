"""Grove manifest — the contract between build and client application.

The manifest maps routes to content-addressed blobs, carries card metadata
for rendering before blobs download, and declares the loading strategy.
"""
import json
from datetime import datetime, timezone
from pathlib import Path


def build_manifest(
    *,
    entries: list[dict],
    assets: list[dict],
    build_hash: str,
    loading_strategy: str,
    priority_count: int,
) -> dict:
    """Assemble the manifest dict from build outputs.

    entries: list of dicts with route, blob, hash, priority, type, title,
             excerpt, date, section, tags, og.
    assets: list of dicts with path, mime, and optional width, height.
    """
    manifest_entries = []
    for e in entries:
        entry = {
            "route": e["route"],
            "blob": e["blob"],
            "hash": e["hash"],
            "priority": e["priority"],
            "type": e["type"],
        }
        # Card metadata — present for posts, section indexes
        for field in ("title", "excerpt", "date", "section", "tags", "og"):
            if field == "date":
                val = e.get("publish_date", "")
                if val:
                    entry["date"] = str(val)
            elif field in e:
                entry[field] = e[field]
        # Layout, width, and theme — router applies these to the body for instant CSS
        # (layout = chrome, width = content column; orthogonal).
        entry["layout"] = e.get("layout", "")
        entry["width"] = e.get("width", "content")
        entry["theme"] = e.get("theme", "")
        manifest_entries.append(entry)

    return {
        "version": build_hash,
        "build_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "encrypted": False,
        "loading": {
            "strategy": loading_strategy,
            "priority_count": priority_count,
        },
        "entries": manifest_entries,
        "assets": assets,
    }


def write_manifest(manifest: dict, dist: Path) -> None:
    """Write manifest.json to dist/."""
    path = dist / "manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
