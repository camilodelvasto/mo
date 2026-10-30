"""Grove image processor — build-time responsive variant generation.

Generates sized variants (WebP + original format) for each image in assets/.
Produces an in-memory manifest keyed by source-relative path. The manifest
is the contract between processing and rendering — render.py reads it to
emit <picture> elements, _og_tags reads it to select the OG-safe variant.

Passthrough: SVG and GIF are copied unchanged (no variants).
No upscaling: variants are only generated for widths <= source width.
Cache: content-hash per source file; unchanged images skip regeneration.
"""
import hashlib
import json
import re
from pathlib import Path
from PIL import Image as PILImage


_WIDTHS = [480, 960, 1440]
_PASSTHROUGH_EXTS = {".svg", ".gif"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}

FORMAT_TO_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "svg": "image/svg+xml",
    "avif": "image/avif",
    "ico": "image/x-icon",
}

# Regex for finding image refs in markdown/HTML
_MD_IMG_RE = re.compile(r'!\[[^\]]*\]\((assets/[^)]+)\)')
_HTML_IMG_RE = re.compile(r'<img\s[^>]*src="(assets/[^"]+)"')

# OG minimum width for large card format
_OG_MIN_WIDTH = 1200


def _compute_image_hash(path: Path) -> str:
    """SHA-256 of file contents, truncated to 12 hex chars."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:12]


def _scan_post_image_refs(posts: list[dict]) -> dict[str, list[str]]:
    """Scan all post markdown bodies for image references.

    Returns dict mapping asset path -> list of post slugs that reference it.
    Only matches paths starting with 'assets/' — external URLs are ignored.
    """
    refs: dict[str, list[str]] = {}
    for post in posts:
        body = post.get("body", "")
        slug = post.get("slug", "")
        found = set()
        for match in _MD_IMG_RE.finditer(body):
            found.add(match.group(1))
        for match in _HTML_IMG_RE.finditer(body):
            found.add(match.group(1))
        for asset_path in found:
            refs.setdefault(asset_path, [])
            if slug and slug not in refs[asset_path]:
                refs[asset_path].append(slug)
    return refs


def _variant_filename(stem: str, width: int, fmt: str) -> str:
    """Generate variant filename: photo-480w.webp"""
    return f"{stem}-{width}w.{fmt}"


def _normalize_format(ext: str) -> str:
    """Normalize extension to format name. .jpeg -> jpg"""
    ext = ext.lower().lstrip(".")
    if ext == "jpeg":
        return "jpg"
    return ext


def _generate_variants(source_path: Path, dist_assets: Path, stem: str,
                       source_format: str, width: int, height: int) -> list[dict]:
    """Generate sized variants for a single image. Returns list of variant dicts."""
    variants = []
    img = PILImage.open(source_path)
    # Convert palette images to RGBA/RGB before any processing
    if img.mode == "P":
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if source_format == "png" else "RGB")

    for target_width in _WIDTHS:
        if target_width >= width:
            continue  # No upscaling

        ratio = target_width / width
        target_height = round(height * ratio)
        resized = img.resize((target_width, target_height), PILImage.LANCZOS)

        # WebP variant
        webp_name = _variant_filename(stem, target_width, "webp")
        webp_path = dist_assets / webp_name
        # Convert RGBA to RGB for WebP if no actual transparency
        webp_img = resized
        if webp_img.mode == "RGBA":
            webp_img = webp_img.convert("RGB")
        webp_img.save(webp_path, "WEBP", quality=85)
        variants.append({
            "path": f"assets/{webp_name}",
            "width": target_width,
            "format": "webp",
            "encrypted": False,
        })

        # Original format variant
        orig_fmt = source_format
        save_fmt = "JPEG" if orig_fmt == "jpg" else orig_fmt.upper()
        orig_name = _variant_filename(stem, target_width, orig_fmt)
        orig_path = dist_assets / orig_name
        save_img = resized
        if save_fmt == "JPEG" and save_img.mode == "RGBA":
            save_img = save_img.convert("RGB")
        save_kwargs = {"quality": 85} if save_fmt in ("JPEG", "WEBP") else {}
        save_img.save(orig_path, save_fmt, **save_kwargs)
        variants.append({
            "path": f"assets/{orig_name}",
            "width": target_width,
            "format": orig_fmt,
            "encrypted": False,
        })

    img.close()
    return variants


def process_images(assets_dir: Path, dist: Path, posts: list[dict],
                   previous_manifest: dict | None = None) -> dict:
    """Process all images in assets_dir, generate variants in dist/assets/.

    Returns manifest dict keyed by source-relative path (e.g. "assets/photo.png").
    Writes image-manifest.json to dist/assets/ for next-build cache.
    """
    dist_assets = dist / "assets"
    if not dist_assets.exists():
        dist_assets.mkdir(parents=True)

    # Scan posts for image references
    post_refs = _scan_post_image_refs(posts)

    # Find OG images referenced in grove config (passed via posts with og field)
    og_images = set()
    for post in posts:
        og = post.get("og")
        if og and "image" in og:
            og_images.add(og["image"])

    manifest: dict = {}
    prev = previous_manifest or {}

    for path in sorted(assets_dir.iterdir()):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in _IMAGE_EXTS:
            continue

        asset_key = f"assets/{path.name}"
        source_hash = _compute_image_hash(path)
        post_slugs = post_refs.get(asset_key, [])
        fmt = _normalize_format(ext)

        # Passthrough: SVG and GIF
        if ext in _PASSTHROUGH_EXTS:
            manifest[asset_key] = {
                "source_hash": source_hash,
                "post_slugs": post_slugs,
                "passthrough": True,
                "encrypted": False,
                "original": {
                    "path": asset_key,
                    "format": fmt,
                    "og_safe": False,
                },
            }
            continue

        # Check cache — skip if unchanged
        prev_entry = prev.get(asset_key)
        if prev_entry and prev_entry.get("source_hash") == source_hash:
            # Reuse previous manifest entry but update post_slugs
            entry = {**prev_entry, "post_slugs": post_slugs}
            manifest[asset_key] = entry
            continue

        # Read dimensions
        with PILImage.open(path) as img:
            width, height = img.size

        # OG size warning
        is_og = asset_key in og_images
        if is_og and width < _OG_MIN_WIDTH:
            print(f"build warn: {asset_key} is {width}px wide; "
                  f"OG images should be at least {_OG_MIN_WIDTH}px for large card format")

        # Generate variants
        stem = path.stem
        variants = _generate_variants(path, dist_assets, stem, fmt, width, height)

        manifest[asset_key] = {
            "source_hash": source_hash,
            "post_slugs": post_slugs,
            "passthrough": False,
            "encrypted": False,
            "original": {
                "path": asset_key,
                "width": width,
                "height": height,
                "format": fmt,
                "og_safe": fmt in ("png", "jpg", "jpeg"),
            },
            "variants": variants,
        }

    # Write manifest to dist for next-build cache
    manifest_path = dist_assets / "image-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return manifest
