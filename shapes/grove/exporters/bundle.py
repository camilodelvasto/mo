"""Bundle collector — gather rendered pages into a single JSON structure for encryption."""
import json


def collect_bundle(pages: dict, search_index: list, first_load_index: list,
                   *, asset_manifest: dict | None = None,
                   asset_salt: str | None = None) -> str:
    """Collect all rendered content into a JSON string.

    pages — dict of path → { title, main, layout, toc? }
    search_index — list of search index entries
    first_load_index — list of first-load index entries
    asset_manifest — optional dict of asset paths → metadata (variants, hashes)
    asset_salt — optional base64-encoded salt for deriving asset decryption keys

    Returns a JSON string ready for encryption.
    """
    bundle = {
        "pages": pages,
        "searchIndex": search_index,
        "firstLoadIndex": first_load_index,
    }
    if asset_manifest is not None:
        bundle["assetManifest"] = asset_manifest
    if asset_salt is not None:
        bundle["assetSalt"] = asset_salt
    return json.dumps(bundle, ensure_ascii=False)
