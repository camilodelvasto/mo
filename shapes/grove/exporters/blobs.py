"""Content-addressed blob writing.

Each rendered HTML page is hashed (SHA-256, first 16 hex chars) and written
to dist/blobs/ as {hash}.bin. The hash is of the content, not the route —
blob names reveal nothing about site structure.
"""
import hashlib
from pathlib import Path


def content_hash(text: str) -> str:
    """SHA-256 of UTF-8 text, truncated to 16 hex chars."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def write_blobs(pages: dict[str, str], blobs_dir: Path) -> dict[str, dict]:
    """Write rendered HTML pages as content-addressed blobs.

    pages: dict of route → HTML string
    blobs_dir: output directory for blob files

    Returns dict of route → { blob: "hash.bin", hash: "full_sha256_prefix" }
    Deduplicates: identical content produces one file referenced by multiple routes.
    """
    blobs_dir.mkdir(parents=True, exist_ok=True)

    result = {}
    for route, html in pages.items():
        h = content_hash(html)
        blob_name = f"{h}.bin"
        blob_path = blobs_dir / blob_name

        if not blob_path.exists():
            blob_path.write_text(html, encoding="utf-8")

        result[route] = {"blob": blob_name, "hash": h}

    return result
