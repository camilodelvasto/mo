"""Deck build module — produces static directories from deck bites."""
import datetime
import hashlib
import json
import mimetypes
import re
import shutil
from pathlib import Path

import yaml

from cli.fonts import build_fonts_css
from cli.component_resolver import resolve_component, collect_component_refs


def derive_build_path(content_path: Path, corpus_root: Path) -> Path:
    """Derive the build output directory from a content file path.

    content/business/sensata/pitch.yaml
    → .corpus/shapes/deck/builds/business/sensata/pitch/

    Strips the content/ prefix and file extension, preserves hierarchy.
    """
    rel = content_path.relative_to(corpus_root / "content")
    without_ext = rel.with_suffix("")
    return corpus_root / ".corpus" / "shapes" / "deck" / "builds" / without_ext


def derive_export_path(content_path: Path, instance_name: str, corpus_root: Path) -> Path:
    """Derive the export output directory from a content file path.

    content/business/sensata/pitch.yaml
    → .corpus/shapes/deck/exports/business/sensata/pitch/

    Same rule as derive_build_path but under exports/ instead of builds/.
    """
    rel = content_path.relative_to(corpus_root / "content")
    without_ext = rel.with_suffix("")
    return corpus_root / ".corpus" / "shapes" / instance_name / "exports" / without_ext


def _json_default(obj):
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


_SW_SENTINEL = "const BUILD_VERSION = 'dev';"


def _version_sw(dist: Path, build_hash: str) -> None:
    """Inject build hash into dist/sw.js at the BUILD_VERSION sentinel line."""
    sw_path = dist / "sw.js"
    text = sw_path.read_text(encoding="utf-8")
    if _SW_SENTINEL not in text:
        raise ValueError(
            f"BUILD_VERSION sentinel not found in {sw_path}. "
            f"Expected line: {_SW_SENTINEL}"
        )
    replacement = f"const BUILD_VERSION = '{build_hash}';"
    sw_path.write_text(text.replace(_SW_SENTINEL, replacement), encoding="utf-8")


def _compute_build_hash(dist: Path) -> str:
    """Content hash of every file in dist/ except sw.js."""
    if not dist.exists():
        raise FileNotFoundError(f"Build directory not found: {dist}")

    digest = hashlib.sha256()
    paths = sorted(p for p in dist.rglob("*") if p.is_file() and p.name != "sw.js")
    for p in paths:
        rel = p.relative_to(dist).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\x00")
        digest.update(p.read_bytes())
    return digest.hexdigest()[:12]


def _collect_media_paths(content_data: dict) -> list:
    """Walk the content structure and collect all media path references."""
    paths = []
    slides = content_data.get("slides", [])
    for slide in slides:
        content = slide.get("content", {})
        if isinstance(content, dict):
            _extract_media(content, paths)
        for side in ("left", "right"):
            side_data = slide.get(side, {})
            if isinstance(side_data, dict):
                side_content = side_data.get("content", {})
                if isinstance(side_content, dict):
                    _extract_media(side_content, paths)
        for cell in slide.get("cells", []):
            cell_content = cell.get("content", {})
            if isinstance(cell_content, dict):
                _extract_media(cell_content, paths)
    return paths


def _extract_media(content: dict, paths: list):
    """Extract media paths from a content block."""
    media = content.get("media")
    if isinstance(media, str) and media:
        paths.append(media)
    elif isinstance(media, dict):
        src = media.get("src")
        if src:
            paths.append(src)
    body = content.get("body", "")
    if isinstance(body, str):
        for m in re.finditer(r'::media\{src="([^"]+)"', body):
            paths.append(m.group(1))
        for m in re.finditer(r'!\[.*?\]\(([^)]+)\)', body):
            paths.append(m.group(1))


_OWNED_SPA_SENTINEL = "const OWNED_SPA_ROOTS = [];"
_PRECACHE_CONTENT_SENTINEL = "const PRECACHE_CONTENT = [];"
_LOCAL_FIRST_SENTINEL = "const LOCAL_FIRST = false;"

_GRAVESTONE_SW = """\
// Gravestone SW — unregisters itself and purges its caches.
// Shipped when service_worker: false in the target environment.
//
// No fetch handler — all requests pass through to network.
// This is intentional: skipWaiting() + clients.claim() means existing
// clients are claimed by this SW immediately. Without a fetch handler,
// claimed clients hit the network directly — correct behavior.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.map(k => caches.delete(k))))
      .then(() => self.clients.claim())
      .then(() => self.registration.unregister())
  );
});
"""


def _inject_local_first(dist: Path, local_first: bool) -> None:
    """Inject LOCAL_FIRST flag into dist/sw.js."""
    sw_path = dist / "sw.js"
    text = sw_path.read_text(encoding="utf-8")
    if _LOCAL_FIRST_SENTINEL not in text:
        raise ValueError(
            f"LOCAL_FIRST sentinel not found in {sw_path}. "
            f"Expected line: {_LOCAL_FIRST_SENTINEL}"
        )
    replacement = f"const LOCAL_FIRST = {'true' if local_first else 'false'};"
    sw_path.write_text(text.replace(_LOCAL_FIRST_SENTINEL, replacement), encoding="utf-8")


def _collect_precache_content(build_dir: Path) -> list:
    """Collect content-specific asset paths relative to build_dir for SW precaching.

    Includes: theme/style.css, fonts/, data/ (media), components/.
    Excludes files already in the hardcoded STATIC_ASSETS list.
    """
    paths = []
    # theme/style.css (optional — only if the theme ships one)
    if (build_dir / "theme" / "style.css").exists():
        paths.append("/theme/style.css")
    # fonts
    fonts_dir = build_dir / "fonts"
    if fonts_dir.is_dir():
        for f in fonts_dir.rglob("*"):
            if f.is_file() and f.suffix in (".css", ".woff2", ".woff", ".ttf", ".otf"):
                paths.append("/" + f.relative_to(build_dir).as_posix())
    # media (data/ directory)
    data_dir = build_dir / "data"
    if data_dir.is_dir():
        for f in data_dir.rglob("*"):
            if f.is_file():
                paths.append("/" + f.relative_to(build_dir).as_posix())
    # components
    comp_dir = build_dir / "components"
    if comp_dir.is_dir():
        for f in comp_dir.rglob("*"):
            if f.is_file():
                paths.append("/" + f.relative_to(build_dir).as_posix())
    return sorted(paths)


_OG_WIDTH = 1200


def _resize_og_image(src: Path, dest: Path) -> None:
    """Resize image to OG-friendly dimensions (1200px wide, quality 80)."""
    from PIL import Image as PILImage

    img = PILImage.open(src)
    width, height = img.size
    if width > _OG_WIDTH:
        ratio = _OG_WIDTH / width
        target_height = round(height * ratio)
        img = img.resize((_OG_WIDTH, target_height), PILImage.LANCZOS)
    if img.mode == "RGBA":
        img = img.convert("RGB")
    fmt = src.suffix.lstrip(".").lower()
    save_fmt = "JPEG" if fmt in ("jpg", "jpeg") else fmt.upper()
    img.save(dest, save_fmt, quality=80)


def _build_og_tags(content_data: dict, base_url: str) -> str:
    """Build OG meta tag HTML from content og block."""
    og = content_data.get("og")
    if not og:
        return ""
    title = og.get("title", content_data.get("title", ""))
    description = og.get("description", "")
    image = og.get("image", "")
    tags = []
    if title:
        tags.append(f'<meta property="og:title" content="{title}">')
    if description:
        tags.append(f'<meta property="og:description" content="{description}">')
    if image:
        image_url = f"{base_url}/og/{Path(image).name}" if base_url else f"./og/{Path(image).name}"
        tags.append(f'<meta property="og:image" content="{image_url}">')
    tags.append('<meta property="og:type" content="website">')
    if base_url:
        tags.append(f'<meta property="og:url" content="{base_url}">')
    return "\n  ".join(tags)


def build(
    content_path: Path,
    instance_name: str,
    corpus_root: Path,
    encrypted: bool = False,
    mnemonic: str = None,
    rotate: bool = False,
    service_worker: bool = True,
    base_url: str = "",
    local_first: bool = False,
) -> tuple:
    """Build a static directory from a deck bite.

    Returns (build_dir, mnemonic_or_none).
    """
    shape_path = corpus_root / "shapes" / instance_name

    content_data = yaml.safe_load(content_path.read_text())
    theme_ref = content_data.get("theme")
    if not theme_ref:
        raise ValueError(f"No theme field in {content_path}")

    # Theme is a path relative to the content file
    theme_src = (content_path.parent / theme_ref).resolve()
    if not theme_src.is_dir():
        raise FileNotFoundError(
            f"Theme directory not found: {theme_src} "
            f"(resolved from '{theme_ref}' relative to {content_path.parent})"
        )

    build_dir = derive_build_path(content_path, corpus_root)
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    # 1. content.json
    content_json = json.dumps(content_data, default=_json_default, ensure_ascii=False)
    if encrypted:
        content_json, mnemonic_out = _build_encrypted(content_json, content_data, mnemonic, rotate)
    else:
        mnemonic_out = None
    (build_dir / "content.json").write_text(content_json)

    # 2. theme/tokens.json
    theme_dir = build_dir / "theme"
    theme_dir.mkdir()
    tokens_path = theme_src / "tokens.yaml"
    if not tokens_path.exists():
        raise FileNotFoundError(f"tokens.yaml not found in theme directory: {theme_src}")
    tokens_data = yaml.safe_load(tokens_path.read_text())
    (theme_dir / "tokens.json").write_text(json.dumps(tokens_data, ensure_ascii=False))

    # 3. theme/style.css
    css_path = theme_src / "style.css"
    if css_path.exists():
        shutil.copy2(css_path, theme_dir / "style.css")

    # 3b. theme/favicon files
    for favicon_name in ("favicon.svg", "favicon.ico", "apple-touch-icon.png"):
        fav_path = theme_src / favicon_name
        if fav_path.exists():
            shutil.copy2(fav_path, theme_dir / favicon_name)

    # 4. renderer/core/ files — rewrite absolute paths to relative in index.html
    import time
    bust = str(int(time.time()))
    core_dir = shape_path / "renderer" / "core"
    for item in core_dir.iterdir():
        if item.name == "vendor":
            shutil.copytree(item, build_dir / "vendor")
        elif item.name == "index.html":
            html = item.read_text()
            # Rewrite absolute paths to relative so subdirectory deploys work
            html = html.replace('href="/', 'href="./').replace('src="/', 'src="./')
            html = html.replace("url('/", "url('./")
            # Cache-bust script/stylesheet references with build timestamp
            html = html.replace('.js"', f'.js?v={bust}"')
            html = html.replace('.css"', f'.css?v={bust}"')
            # Inject OG meta tags
            og_html = _build_og_tags(content_data, base_url)
            html = html.replace("<!-- og:meta -->", og_html)
            # Set page title from content
            page_title = content_data.get("title", "Deck")
            html = html.replace("<title>Deck</title>", f"<title>{page_title}</title>")
            (build_dir / "index.html").write_text(html)
        elif item.suffix == ".js":
            js = item.read_text()
            js = js.replace(".js'", f".js?v={bust}'")
            (build_dir / item.name).write_text(js)
        elif item.is_file():
            shutil.copy2(item, build_dir / item.name)

    # 5. fonts/ + fonts.css
    fonts_src = shape_path / "fonts"
    if fonts_src.is_dir():
        shutil.copytree(fonts_src, build_dir / "fonts")
        (build_dir / "fonts" / "fonts.css").write_text(build_fonts_css(build_dir / "fonts", url_prefix="."))

    # 6. media/artifacts → data/
    media_paths = _collect_media_paths(content_data)
    if media_paths:
        for media_path in media_paths:
            src = corpus_root / media_path
            if src.exists():
                dest = build_dir / "data" / media_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.suffix == ".html":
                    # Rewrite absolute paths in artifact HTML so they resolve
                    # correctly when deployed at a subdirectory.
                    depth = len(dest.relative_to(build_dir).parts) - 1
                    prefix = "../" * depth
                    html = src.read_text()
                    html = html.replace('href="/', f'href="{prefix}')
                    html = html.replace('src="/', f'src="{prefix}')
                    html = html.replace("url('/", f"url('{prefix}")
                    dest.write_text(html)
                else:
                    shutil.copy2(src, dest)

    # 6b. OG image → og/ (resized to 1200px wide, quality 80)
    og = content_data.get("og", {})
    og_image = og.get("image", "")
    if og_image:
        og_src = corpus_root / og_image
        if og_src.exists():
            og_dir = build_dir / "og"
            og_dir.mkdir(exist_ok=True)
            _resize_og_image(og_src, og_dir / og_src.name)

    # 6c. Encrypt assets — only when SW is active to decrypt on fetch.
    # Without the SW, encrypted assets are unreachable (404). Content.json
    # envelope encryption still works (gate page decrypts client-side).
    if encrypted and service_worker:
        _encrypt_assets(build_dir, mnemonic_out or mnemonic)

    # 7. components/ — resolve and copy referenced components
    component_refs = collect_component_refs(content_data)
    for comp_name in component_refs:
        comp_dir = resolve_component(
            comp_name, corpus_root=corpus_root, shape_path=shape_path,
        )
        dest = build_dir / "components" / comp_name
        dest.mkdir(parents=True, exist_ok=True)
        for fname in ("render.js", "style.css", "component.yaml"):
            src_file = comp_dir / fname
            if src_file.exists():
                shutil.copy2(src_file, dest / fname)

    # 8. Service worker — gate on target flag
    sw_src = shape_path / "renderer" / "shell-web" / "sw.js"
    if service_worker and sw_src.exists():
        shutil.copy2(sw_src, build_dir / "sw.js")
        build_hash = _compute_build_hash(build_dir)
        _version_sw(build_dir, build_hash)
        _inject_local_first(build_dir, local_first)
        # Inject declarations
        sw_path = build_dir / "sw.js"
        text = sw_path.read_text(encoding="utf-8")
        text = text.replace(_OWNED_SPA_SENTINEL,
                            "const OWNED_SPA_ROOTS = ['/'];")
        # Inject content-specific precache paths
        precache_paths = _collect_precache_content(build_dir)
        precache_js = "const PRECACHE_CONTENT = " + json.dumps(precache_paths) + ";"
        text = text.replace(_PRECACHE_CONTENT_SENTINEL, precache_js)
        sw_path.write_text(text, encoding="utf-8")
        # Generate manifest for local_first mode
        if local_first:
            manifest = _build_manifest(build_dir, build_hash)
            (build_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2)
            )
    elif not service_worker and sw_src.exists():
        (build_dir / "sw.js").write_text(_GRAVESTONE_SW, encoding="utf-8")

    return build_dir, mnemonic_out


def _build_encrypted(content_json, content_data, mnemonic_phrase, rotate):
    """Encrypt content JSON. Returns (envelope_json, mnemonic).

    If mnemonic_phrase is provided and rotate is False, reuse it.
    If mnemonic_phrase is None or rotate is True, generate a new one.
    Always prints the mnemonic.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
    except ImportError:
        raise SystemExit(
            "Encrypted builds require additional dependencies. "
            "Run: pip install cryptography mnemonic"
        )

    import base64
    import os

    if not mnemonic_phrase or rotate:
        try:
            from mnemonic import Mnemonic
        except ImportError:
            raise SystemExit(
                "Encrypted builds require additional dependencies. "
                "Run: pip install cryptography mnemonic"
            )
        m = Mnemonic("english")
        mnemonic_phrase = m.generate(strength=128)
        if rotate:
            print("Warning: existing access codes for this deck will stop working.\n")

    print(f"\nAccess code: {mnemonic_phrase}")
    print(f"This is stored in .corpus/publishes/\n")

    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = kdf.derive(mnemonic_phrase.encode())

    iv = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, content_json.encode(), None)

    envelope = {
        "encrypted": True,
        "meta": {"title": content_data.get("title", "")},
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "payload": base64.b64encode(ciphertext).decode(),
    }

    return json.dumps(envelope, ensure_ascii=False), mnemonic_phrase


def _encrypt_assets(build_dir: Path, mnemonic: str) -> str:
    """Encrypt all files in data/ and og/ directories.

    Replaces each file with a .enc envelope. One shared salt for all assets,
    unique IV per file. Writes asset-salt.json with the shared salt.

    Returns the base64-encoded shared salt.
    """
    import base64
    import os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    salt = os.urandom(16)
    salt_b64 = base64.b64encode(salt).decode()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32,
        salt=salt, iterations=100000,
    )
    key = kdf.derive(mnemonic.encode())
    aesgcm = AESGCM(key)

    for subdir in ("data", "og"):
        target = build_dir / subdir
        if not target.is_dir():
            continue
        for f in list(target.rglob("*")):
            if not f.is_file():
                continue
            plaintext = f.read_bytes()
            iv = os.urandom(12)
            ciphertext = aesgcm.encrypt(iv, plaintext, None)
            envelope = {
                "encrypted": True,
                "salt": salt_b64,
                "iv": base64.b64encode(iv).decode(),
                "payload": base64.b64encode(ciphertext).decode(),
            }
            enc_path = f.with_name(f.name + ".enc")
            enc_path.write_text(json.dumps(envelope, ensure_ascii=False))
            f.unlink()

    (build_dir / "asset-salt.json").write_text(
        json.dumps({"salt": salt_b64}, ensure_ascii=False)
    )
    return salt_b64


_MANIFEST_EXCLUDE = {"sw.js", "manifest.json"}


def _build_manifest(build_dir: Path, build_hash: str) -> dict:
    """Build a deck manifest — asset inventory for SW precaching.

    Lists every file in build_dir with path, size, and MIME type.
    Excludes sw.js (the SW itself) and manifest.json (circular).
    """
    files = []
    for f in sorted(build_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(build_dir).as_posix()
        if rel in _MANIFEST_EXCLUDE:
            continue
        mime, _ = mimetypes.guess_type(f.name)
        if mime is None:
            mime = "application/octet-stream"
        files.append({
            "path": rel,
            "size": f.stat().st_size,
            "mime": mime,
        })
    return {"version": build_hash, "files": files}


def _collect_encrypted_asset_paths(build_dir: Path) -> list[str]:
    """Collect original (pre-encryption) asset paths from .enc files.

    Returns paths like /data/photo.png (without .enc suffix) relative to build_dir.
    These are the paths the SW should intercept for decrypt-on-fetch.
    """
    paths = []
    for subdir in ("data", "og"):
        target = build_dir / subdir
        if not target.is_dir():
            continue
        for f in target.rglob("*.enc"):
            # Strip .enc to get original path
            original = f.with_suffix("")
            paths.append("/" + original.relative_to(build_dir).as_posix())
    return sorted(paths)
