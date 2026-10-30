"""Grove build orchestrator — content to static site."""
import fnmatch
import hashlib
import json
import shutil
import yaml
from pathlib import Path
from urllib.parse import urlparse

from content import scan_posts, ParseError
from slugs import resolve_slugs, SlugConflictError
from visibility import (filter_for_build, filter_for_index, filter_for_feed,
                        filter_for_sitemap, filter_for_search,
                        filter_for_serve_build, filter_for_serve_index)
from render import (render_post, render_index_page, render_archive_page,
                    render_post_fragment, render_index_fragment, render_archive_fragment)
from og import validate_grove_og, OGError
from rss import generate_rss_xml, generate_json_feed
from sitemap import generate_sitemap
from redirects import generate_redirects_file, generate_caddy_redirects
from indexes import generate_first_load_index, generate_search_index
from collections_mod import load_collections, resolve_collection_posts, CollectionError
from themes import render_theme_css
from render import render_syntax_css
from images import process_images, FORMAT_TO_MIME
from priorities import assign_priorities
from blobs import write_blobs
from manifest import build_manifest, write_manifest
from og_stubs import write_og_stubs, write_full_stubs
from app_shell import render_app_shell
from pages import load_pages
from compose import compose_page, compose_fragment, _page_has_chat_feature


class BuildError(Exception):
    """Raised when the build cannot complete."""


def _load_grove(grove_root: Path) -> dict:
    """Load and validate grove.yaml. Returns grove config dict — read-only downstream."""
    grove_yaml_path = grove_root / "grove.yaml"
    if not grove_yaml_path.exists():
        raise BuildError(f"grove.yaml not found in {grove_root}")
    grove = yaml.safe_load(grove_yaml_path.read_text(encoding="utf-8"))
    try:
        validate_grove_og(grove)
    except OGError as e:
        raise BuildError(f"og validation failed: {e}") from e
    return grove


def _resolve_posts(grove_root: Path) -> list[dict]:
    """Scan, resolve slugs, normalize dates, sort. Returns sorted post list."""
    posts_dir = grove_root / "posts"
    if not posts_dir.exists():
        raise BuildError(f"posts/ directory not found in {grove_root}")
    try:
        posts = scan_posts(posts_dir)
    except ParseError as e:
        raise BuildError(f"Parse error: {e}") from e
    try:
        posts = resolve_slugs(posts)
    except SlugConflictError as e:
        raise BuildError(f"Duplicate slug: {e}") from e
    for post in posts:
        if "publish_date" in post:
            post["publish_date"] = str(post["publish_date"])
    # Sort descending by date, then sticky posts float to top.
    # Two stable sorts: date first, then sticky — preserves date order within each group.
    posts.sort(key=lambda p: p.get("publish_date") or "", reverse=True)
    posts.sort(key=lambda p: 0 if p.get("sticky") else 1)
    return posts


def _render_posts(build_posts: list[dict], grove: dict, ctx: dict, dist: Path, *, manifest=None) -> None:
    """Render individual post pages to dist/."""
    for post in build_posts:
        url_path = post["url_path"].strip("/")
        post_dir = dist / url_path
        post_dir.mkdir(parents=True, exist_ok=True)
        html = render_post(post, grove, ctx, manifest=manifest)
        (post_dir / "index.html").write_text(html, encoding="utf-8")


def _slug_to_dir(dist: Path, route: str) -> Path:
    rel = route.strip("/")
    return dist if rel == "" else (dist / rel)


def _assert_no_page_post_collision(pages: list[dict], posts: list[dict]) -> None:
    """Raise BuildError if any page route targets the same dist path as a rendered post."""
    post_paths = {p["url_path"].strip("/") for p in posts if "url_path" in p}
    for page in pages:
        norm = page["route"].strip("/")
        if norm in post_paths:
            raise BuildError(
                f"page route '{page['route']}' collides with a post — both target dist/{norm}/"
            )


_CHAT_PERSIST_VALUES = frozenset({"none", "local"})


def _validate_features(features: list[dict]) -> None:
    """Validate declared features. A `type: chat` feature may declare `persist`
    (none | local), `name`, `avatar`, `intro` — an unknown `persist` value fails
    the build, named (no-fallbacks). Unknown feature types are caught at element
    resolution (elements.py); persist is the only field gated here."""
    for f in features:
        if f.get("type") != "chat":
            continue
        # `ask` is mandatory for every chat feature — it names the conversation
        # the chat speaks; without it the feature is inert (no-fallbacks).
        ask = f.get("ask")
        if not isinstance(ask, str) or not ask.strip():
            raise BuildError(
                f"chat feature '{f.get('id')}' is missing a non-empty 'ask' — "
                f"a chat has nothing to talk through without it"
            )
        # `route` is optional (a chat may be an in-page element with no route),
        # but if declared it must be a non-empty string — an empty route would
        # be a chat catch-all that owns the whole site, silently, at serve time.
        if "route" in f:
            route = f.get("route")
            if not isinstance(route, str) or not route.strip():
                raise BuildError(
                    f"chat feature '{f.get('id')}' declares an empty 'route' — "
                    f"a routed chat needs a real path prefix"
                )
        persist = f.get("persist", "none")
        if persist not in _CHAT_PERSIST_VALUES:
            raise BuildError(
                f"chat feature '{f.get('id')}' declares persist: '{persist}' — "
                f"must be one of {sorted(_CHAT_PERSIST_VALUES)}"
            )



def _render_default_home(grove: dict, ctx: dict, dist: Path, posts: list[dict], *, manifest=None) -> None:
    """Render the default post-feed home when no '/' page is declared."""
    ppp = grove.get("defaults", {}).get("posts_per_page")
    html = render_index_page(posts[:ppp] if ppp else posts, grove, ctx, manifest=manifest)
    (dist / "index.html").write_text(html, encoding="utf-8")


def _render_pages(pages: list[dict], grove: dict, ctx: dict, dist: Path, posts: list[dict],
                  *, feature_endpoints: dict, chat_config=None, manifest=None) -> None:
    """Render every declared page to dist/.

    A page with published: false is skipped entirely — no dist/<route>/index.html
    written. Default is True (pages render unless explicitly gated out).
    """
    for page in pages:
        if not page.get("published", True):
            continue
        out_dir = _slug_to_dir(dist, page["route"])
        out_dir.mkdir(parents=True, exist_ok=True)
        html = compose_page(page, grove, ctx, grove_root=ctx["_grove_root"],
                            posts=posts, feature_endpoints=feature_endpoints,
                            chat_config=chat_config, pages=pages)
        (out_dir / "index.html").write_text(html, encoding="utf-8")


def _render_section_indexes(build_posts: list[dict], grove: dict, ctx: dict, dist: Path, *, manifest=None) -> None:
    """Auto-generate section index pages for subdirectories without explicit index.md."""
    sections: dict[str, list[dict]] = {}
    section_has_explicit_index: set[str] = set()
    for post in build_posts:
        cp = post["content_path"]
        if post.get("is_section_index"):
            section_has_explicit_index.add(cp)
        elif "/" in cp:
            section = cp.split("/")[0]
            sections.setdefault(section, []).append(post)

    for section, section_posts in sections.items():
        if section in section_has_explicit_index:
            continue
        section_dir = dist / section
        section_dir.mkdir(parents=True, exist_ok=True)
        section_title = section.replace("-", " ").title()
        section_html = render_index_page(section_posts, grove, ctx, page_title=section_title, manifest=manifest)
        (section_dir / "index.html").write_text(section_html, encoding="utf-8")


def _render_collections(grove_root: Path, build_posts: list[dict], grove: dict, ctx: dict, dist: Path, *, manifest=None) -> None:
    """Render collection pages from content/collections/."""
    collections_dir = grove_root / "content" / "collections"
    collections = load_collections(collections_dir)
    if not collections:
        return
    posts_by_path = {post["content_path"]: post for post in build_posts}
    for coll in collections:
        try:
            coll_posts = resolve_collection_posts(coll, posts_by_path)
        except CollectionError as e:
            raise BuildError(str(e)) from e
        coll_dir = dist / "c" / coll["id"]
        coll_dir.mkdir(parents=True, exist_ok=True)
        coll_html = render_index_page(coll_posts, grove, ctx, page_title=coll["title"], manifest=manifest)
        (coll_dir / "index.html").write_text(coll_html, encoding="utf-8")


def _render_archive(build_posts: list[dict], grove: dict, ctx: dict, dist: Path, *, manifest=None) -> None:
    """Render the archive page."""
    archive_dir = dist / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_html = render_archive_page(build_posts, grove, ctx, manifest=manifest)
    (archive_dir / "index.html").write_text(archive_html, encoding="utf-8")


def _generate_feeds(feed_posts: list[dict], grove: dict, ctx: dict, dist: Path) -> None:
    """Generate RSS and JSON feeds if RSS is configured."""
    # RSS block is genuinely optional — grove may not define it at all.
    rss_config = grove.get("rss")
    if rss_config is None or not rss_config.get("enabled"):
        return
    feed_xml = generate_rss_xml(feed_posts, grove, ctx["base_url"])
    (dist / "feed.xml").write_text(feed_xml, encoding="utf-8")
    feed_json = generate_json_feed(feed_posts, grove, ctx["base_url"])
    (dist / "feed.json").write_text(feed_json, encoding="utf-8")


def _generate_sitemap(sitemap_posts: list[dict], ctx: dict, dist: Path) -> None:
    """Generate sitemap.xml."""
    sitemap_xml = generate_sitemap(sitemap_posts, ctx["base_url"])
    (dist / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")


def _generate_redirects(build_posts: list[dict], dist: Path) -> None:
    """Generate redirect files if any posts have redirects."""
    redirects_text = generate_redirects_file(build_posts)
    if redirects_text:
        (dist / "_redirects").write_text(redirects_text, encoding="utf-8")
    caddy_text = generate_caddy_redirects(build_posts)
    if caddy_text:
        (dist / "redirects.caddy").write_text(caddy_text, encoding="utf-8")


def _generate_search_indexes(index_posts: list[dict], search_posts: list[dict], grove: dict, ctx: dict, dist: Path) -> None:
    """Generate first-load and search JSON indexes."""
    posts_per_page = grove["defaults"]["posts_per_page"]
    base_path = ctx["base_path"]
    first_load = generate_first_load_index(index_posts, posts_per_page, base_path=base_path)
    (dist / "first-load-index.json").write_text(first_load, encoding="utf-8")
    search_index = generate_search_index(search_posts, base_path=base_path)
    (dist / "search-index.json").write_text(search_index, encoding="utf-8")


def _write_syntax_css(dist: Path) -> None:
    """Write Pygments-generated syntax.css for code highlighting."""
    (dist / "syntax.css").write_text(render_syntax_css(), encoding="utf-8")


_GROVE_DYNAMIC_PATHS = ['/feed.xml', '/feed.json', '/sitemap.xml',
                        '/search-index.json', '/first-load-index.json']

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


def _collect_owned_pages(build_posts: list, dist: Path) -> list[str]:
    """Collect all page URLs this grove build produced."""
    pages = {'/'}  # root index
    for post in build_posts:
        pages.add(post['url_path'])
    pages.add('/archive/')
    # Section indexes — directories with index.html that aren't infrastructure
    _infra_dirs = {'archive', 'c', 'theme', 'assets', 'shell-web', 'shell-tauri'}
    for d in sorted(dist.iterdir()):
        if d.is_dir() and d.name not in _infra_dirs and (d / 'index.html').exists():
            pages.add(f'/{d.name}/')
    # Collections
    c_dir = dist / 'c'
    if c_dir.is_dir():
        for d in sorted(c_dir.iterdir()):
            if d.is_dir():
                pages.add(f'/c/{d.name}/')
    return sorted(pages)


def _collect_owned_assets(manifest: dict) -> list[str]:
    """Collect asset paths from image processing manifest for encrypted interception."""
    paths = []
    for _src, entry in manifest.items():
        orig = entry.get('original', {})
        if orig.get('path'):
            paths.append('/' + orig['path'])
        for v in entry.get('variants', []):
            if v.get('path'):
                paths.append('/' + v['path'])
    return paths


def _manifest_assets_from_image_manifest(image_manifest: dict) -> list[dict]:
    """Convert image processing manifest to manifest asset entries.

    The image manifest is the source of truth for which variants exist.
    Only includes variants that were actually generated (no stubs for
    skipped sizes).
    """
    assets = []
    for _src, entry in image_manifest.items():
        orig = entry.get("original", {})
        if not orig.get("path"):
            continue
        fmt = orig.get("format", "")
        asset_entry = {
            "path": orig["path"],
            "mime": FORMAT_TO_MIME.get(fmt, "application/octet-stream"),
        }
        # Only include dimensions when available (passthrough SVG/GIF have none)
        if "width" in orig:
            asset_entry["width"] = orig["width"]
        if "height" in orig:
            asset_entry["height"] = orig["height"]
        assets.append(asset_entry)
        for v in entry.get("variants", []):
            if not v.get("path"):
                continue
            v_fmt = v.get("format", "")
            assets.append({
                "path": v["path"],
                "mime": FORMAT_TO_MIME.get(v_fmt, "application/octet-stream"),
                "width": v.get("width", 0),
            })
    return assets


_OWNED_PAGES_SENTINEL = 'const OWNED_PAGES = [];'
_OWNED_SPA_SENTINEL = 'const OWNED_SPA_ROOTS = [];'
_OWNED_DYNAMIC_SENTINEL = 'const OWNED_DYNAMIC_PATHS = [];'
_OWNED_ASSETS_SENTINEL = 'const OWNED_ASSETS = [];'
_SIBLING_PATHS_SENTINEL = 'const SIBLING_PATHS = [];'
_OPTIONAL_STATIC_SENTINEL = 'const OPTIONAL_STATIC_ASSETS = [];'


def _collect_sibling_paths(corpus_root: Path | None, base_url: str) -> list[str]:
    """Find other groves nested under this grove's base_path, on the same domain.

    Scans infrastructure/targets/ for environments on the same domain whose
    base_path is nested *inside* this grove's base_path. Only nested targets are
    reachable within this grove's service-worker scope (<base>/*); a target
    outside the scope — the root grove at '/', or a peer like '/es' — is never
    seen by this SW. Listing '/' in particular, a prefix of every in-scope path,
    would make the SW pass through its OWN routes.

    Returns each sibling path *relative to this grove's base*, matching how the
    SW prepends BASE_PATH to every declaration (OWNED_PAGES, OWNED_ASSETS, …).
    """
    if not corpus_root:
        return []
    targets_dir = Path(corpus_root) / "infrastructure" / "targets"
    if not targets_dir.exists():
        return []

    parsed = urlparse(base_url)
    my_domain = parsed.hostname
    my_base = parsed.path.rstrip("/")          # '' for the root grove, '/hub' for a subpath
    my_prefix = my_base + "/"                   # '/' for root, '/hub/' for a subpath

    siblings = []
    for target_file in targets_dir.rglob("*.yaml"):
        raw = yaml.safe_load(target_file.read_text())
        if not isinstance(raw, dict) or "environments" not in raw:
            continue
        for env in raw["environments"].values():
            domain = env.get("domain", "")
            bp = env.get("base_path", "")
            if not domain or not bp or domain != my_domain:
                continue
            # Normalize: ensure starts with / and ends with /
            normalized = bp if bp.startswith("/") else "/" + bp
            if not normalized.endswith("/"):
                normalized += "/"
            # Own path, or a target outside this grove's scope → not a sibling.
            if normalized == my_prefix or not normalized.startswith(my_prefix):
                continue
            relative = normalized[len(my_base):]   # strip this grove's base → grove-relative
            if relative not in siblings:
                siblings.append(relative)
    return sorted(siblings)


def _collect_chat_spa_roots(pages: list[dict], grove: dict) -> list[str]:
    """Routes of pages whose body mounts a chat feature.

    A chat page is a client-routed SPA root: its conversation slugs are client
    routes with no static file. The service worker serves the page itself for
    any slug under it, and the page restores the conversation from IndexedDB.
    Derived from the declared pages map — never guessed from directory shape.
    """
    return [p["route"] for p in pages if _page_has_chat_feature(p, grove)]


def _collect_optional_static(dist: Path) -> list[str]:
    """Static assets that exist only for some grove types, listed only when the
    build actually emitted them.

    The local-first manifest (manifest.json) is written for local-first groves
    but absent on plain/MPA groves. The service worker precaches STATIC_ASSETS
    with an atomic addAll, so listing a file that 404s fails the whole install —
    the SW then never activates. Declaring only what exists keeps the precache
    honest (no assumption that a conditional asset is present).
    """
    return ['/manifest.json'] if (dist / 'manifest.json').is_file() else []


def _inject_sw_declarations(dist: Path, pages: list[str], dynamic: list[str],
                            assets: list[str], *, spa_roots: list[str] | None = None,
                            sibling_paths: list[str] | None = None,
                            optional_static: list[str] | None = None) -> None:
    """Inject scope declarations into sw.js via sentinel replacement."""
    sw_path = dist / 'sw.js'
    text = sw_path.read_text(encoding='utf-8')
    text = text.replace(_OPTIONAL_STATIC_SENTINEL,
                        f'const OPTIONAL_STATIC_ASSETS = {json.dumps(optional_static or [])};')
    text = text.replace(_OWNED_PAGES_SENTINEL,
                        f'const OWNED_PAGES = {json.dumps(pages)};')
    text = text.replace(_OWNED_SPA_SENTINEL,
                        f'const OWNED_SPA_ROOTS = {json.dumps(spa_roots or [])};')
    text = text.replace(_OWNED_DYNAMIC_SENTINEL,
                        f'const OWNED_DYNAMIC_PATHS = {json.dumps(dynamic)};')
    text = text.replace(_OWNED_ASSETS_SENTINEL,
                        f'const OWNED_ASSETS = {json.dumps(assets)};')
    text = text.replace(_SIBLING_PATHS_SENTINEL,
                        f'const SIBLING_PATHS = {json.dumps(sibling_paths or [])};')
    sw_path.write_text(text, encoding='utf-8')


def _write_gravestone_sw(dist: Path) -> None:
    """Write a gravestone SW that unregisters itself and purges caches."""
    (dist / 'sw.js').write_text(_GRAVESTONE_SW, encoding='utf-8')


_SW_SENTINEL = "const BUILD_VERSION = 'dev';"
_BUILD_HASH_PLACEHOLDER = "__BUILD_HASH__"


def _stamp_build_hash_in_html(dist: Path, build_hash: str) -> None:
    """Replace __BUILD_HASH__ placeholder in all HTML files with the real hash."""
    for html_file in dist.rglob("*.html"):
        text = html_file.read_text(encoding="utf-8")
        if _BUILD_HASH_PLACEHOLDER in text:
            html_file.write_text(
                text.replace(_BUILD_HASH_PLACEHOLDER, build_hash), encoding="utf-8"
            )


def _version_sw(dist: Path, build_hash: str) -> None:
    """Inject build hash into dist/sw.js at the BUILD_VERSION sentinel line.

    Full-line match prevents accidental replacement of 'dev' elsewhere in
    sw.js (comments, log lines, etc.). Raises ValueError if the sentinel
    isn't present — per project principle (no fallbacks), a missing
    sentinel is a real error, not something to silently work around.
    """
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
    """Content hash of every file in dist/ except sw.js.

    Deterministic across platforms: walks paths in sorted order and feeds
    `relative_path + \0 + bytes` into a single SHA-256 digest. Truncates
    to 12 hex chars — enough identity for cache invalidation without
    bloating log lines.

    sw.js is excluded because it's the cache manager, not a cached asset:
    the hash is about to be written into it, so including it creates a
    chicken-and-egg.

    Raises FileNotFoundError if dist does not exist — the build flow must
    have produced dist before this is called.
    """
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


def _copy_grove_assets(grove_root: Path, dist: Path) -> None:
    """Copy grove-level static assets (images, fonts, etc.) to dist.

    Convention: {grove_root}/assets/ → dist/assets/. Skipped if no assets dir.
    """
    assets = grove_root / "assets"
    if not assets.is_dir():
        return
    dest = dist / "assets"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(assets, dest)


# Never shipped: guides, tests, the node-only DOM/IDB shims the tests import,
# and bytecode caches.
_NOT_SHIPPED = ("*.md", "test_*", "_*.mjs", "__pycache__")


def _not_shipped(name: str) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in _NOT_SHIPPED)


def _copy_renderer_assets(dist: Path, shape_path: Path) -> None:
    """Copy renderer core and shell-web assets into dist for static serving.

    Dev server serves these dynamically from renderer/; deployed sites need
    them baked into dist. Excludes *.md (guides), tests, `_*.mjs` test shims,
    __pycache__, server.py, and index.html (we generate our own).
    """
    renderer = shape_path / "renderer"

    core = renderer / "core"
    for item in core.iterdir():
        if item.name == "index.html":
            continue  # generated by build, not copied
        if _not_shipped(item.name):
            continue
        dest = dist / item.name
        if item.is_dir():
            shutil.copytree(item, dest, ignore=shutil.ignore_patterns(*_NOT_SHIPPED))
        else:
            shutil.copy2(item, dest)

    # shell-web/ goes to dist/shell-web/ — app.js imports ./shell-web/transport.js.
    # Exception: sw.js must be at dist root so its SW scope covers the whole
    # base_path (SWs can only control requests under their own directory).
    shell_web = renderer / "shell-web"
    shell_dest = dist / "shell-web"
    shell_dest.mkdir(exist_ok=True)
    for item in shell_web.iterdir():
        if item.name == "server.py" or _not_shipped(item.name):
            continue
        if item.name == "sw.js":
            shutil.copy2(item, dist / "sw.js")
            continue
        if item.is_dir():
            shutil.copytree(item, shell_dest / item.name, ignore=shutil.ignore_patterns(*_NOT_SHIPPED))
        else:
            shutil.copy2(item, shell_dest / item.name)

    # shell-tauri/ — app.js dynamic-imports ./shell-tauri/transport.js when
    # running under Tauri. Copy so static sites don't 404 when Tauri detection
    # fails mid-flight (and to keep the layout consistent).
    shell_tauri = renderer / "shell-tauri"
    if shell_tauri.is_dir():
        shell_tauri_dest = dist / "shell-tauri"
        shell_tauri_dest.mkdir(exist_ok=True)
        for item in shell_tauri.iterdir():
            if _not_shipped(item.name):
                continue
            if item.is_file():
                shutil.copy2(item, shell_tauri_dest / item.name)


def _copy_favicon_files(dist: Path, themes_dir: Path, shape_themes_dir: Path | None = None) -> None:
    """Copy theme favicon files into dist/theme/.

    Resolution: content theme first, shape theme as fallback.
    """
    theme_out = dist / "theme"
    theme_out.mkdir(exist_ok=True)
    candidates = [themes_dir / "default"]
    if shape_themes_dir:
        candidates.append(shape_themes_dir / "default")
    for favicon_name in ("favicon.svg", "favicon.ico", "apple-touch-icon.png"):
        for theme_dir in candidates:
            fav_path = theme_dir / favicon_name
            if fav_path.exists():
                shutil.copy2(fav_path, theme_out / favicon_name)
                break


def _copy_theme_fonts(dist: Path, themes_dir: Path) -> None:
    """Copy theme font files into dist/fonts/."""
    fonts_src = themes_dir / "default" / "fonts"
    if not fonts_src.is_dir():
        return
    fonts_dst = dist / "fonts"
    if fonts_dst.exists():
        shutil.rmtree(fonts_dst)
    shutil.copytree(fonts_src, fonts_dst, ignore=shutil.ignore_patterns("*.txt", "*.md"))


def _derive_base_path(base_url: str) -> str:
    """Extract the path portion from base_url, without trailing slash.

    https://moui.codeberg.page/grove → /grove
    https://example.com/          → ""
    http://localhost:4200         → ""
    """
    parsed = urlparse(base_url)
    return parsed.path.rstrip("/")


# The chat feature's localized strings. Required ONLY for a grove that declares a
# chat feature (so chat-less groves are never burdened), and the client reads them
# with no hardcoded fallback — so they must be present. MUST match the keys
# chat.js consumes (renderer/core/components/chat.js).
CHAT_STRING_KEYS = frozenset({
    "chat_input_placeholder", "chat_send", "chat_working", "chat_sources",
    "chat_error_refused", "chat_error_failed",
    # Sidebar (Task 6): conversation list, new chat, and the delete confirm.
    "chat_sidebar_label", "chat_new", "chat_delete", "chat_delete_cancel",
    "chat_delete_confirm",
    # Secret-gate + first-class ask states (each true at the moment shown).
    "chat_gate_prompt", "chat_gate_submit", "chat_gate_rejected", "chat_over_limit",
    "chat_revoked", "chat_offline", "chat_unavailable", "chat_not_permitted",
    # Stop button aria-label (Task 9 morphing stop button).
    "chat_stop",
    # Attachment composer (Task 5): button label, remove, and error states.
    "chat_attach", "chat_attach_remove", "chat_attach_too_large",
    "chat_attach_wrong_type", "chat_attach_too_many", "chat_attach_failed",
    "chat_attach_missing", "chat_attach_not_saved", "chat_attach_unavailable",
})


def _feature_required_strings(features) -> set:
    """The string keys a grove's declared features demand on top of the base set."""
    required: set = set()
    if any(f.get("type") == "chat" for f in features):
        required |= CHAT_STRING_KEYS
    return required


def _build_ctx(base_url: str, themes_dir: Path, *, on_clear: str, crawlable: str,
               features=()) -> dict:
    """Assemble build-derived context distinct from user-authored grove config.

    Holds values computed at build time: the canonical URL, the derived URL
    sub-path, and the inlined theme CSS. Kept separate from grove so the
    user's grove.yaml dict is never mutated downstream. `features` (the grove's
    declared features) gate feature-specific required strings.
    """
    from cli.fonts import build_fonts_css
    from strings import load_strings

    base_path = _derive_base_path(base_url)
    fonts_dir = themes_dir / "default" / "fonts"
    font_prefix = f"{base_path}/fonts" if base_path else "/fonts"
    fonts_css = build_fonts_css(fonts_dir, url_prefix=font_prefix) if fonts_dir.is_dir() else ""

    languages_dir = Path(__file__).resolve().parent.parent / "languages"
    icons_dir = Path(__file__).resolve().parent.parent / "icons"
    strings = load_strings(themes_dir, languages_dir,
                           extra_required=_feature_required_strings(features))

    return {
        "base_url": base_url,
        "base_path": base_path,
        "theme_css": render_theme_css(themes_dir),
        "fonts_css": fonts_css,
        "on_clear": on_clear,
        "crawlable": crawlable,
        "strings": strings,
        "icons_dir": icons_dir,
    }


def derive_build_path(grove_root: Path, corpus_root: Path) -> Path:
    """Derive build output directory following corpus convention.

    content/grove/ → .corpus/shapes/grove/builds/grove/
    Strips content/ prefix, preserves hierarchy.
    """
    rel = grove_root.relative_to(corpus_root / "content")
    return corpus_root / ".corpus" / "shapes" / "grove" / "builds" / rel


def _build_encrypted(grove_root: Path, grove: dict, ctx: dict, posts: list,
                     build_posts: list, dist: Path, corpus_root,
                     themes_dir: Path,
                     *, mnemonic: str, rotate: bool,
                     manifest: dict | None = None,
                     service_worker: bool = True) -> tuple:
    """Whole-grove encrypted build. Produces gate page + encrypted bundle.

    Renders all pages into memory, collects into a JSON bundle, encrypts,
    and writes gate index.html + bundle.enc. No per-page HTML, no feeds,
    no sitemap, no JSON index files, no _redirects.
    """
    import re as _re
    from encrypt import make_encryptor, generate_mnemonic
    from bundle import collect_bundle
    from indexes import generate_first_load_index_data, generate_search_index_data
    from render import render_gate_page

    index_posts = filter_for_index(posts)
    search_posts = filter_for_search(posts)

    if not mnemonic or rotate:
        mnemonic = generate_mnemonic()

    # Create asset encryptor if there are assets to encrypt
    asset_encryptor = None
    asset_salt = None
    if manifest:
        from encrypt import make_asset_encryptor
        asset_encryptor, asset_salt = make_asset_encryptor(mnemonic)

    # Render all post pages into memory
    pages = {}
    for post in build_posts:
        html = render_post(post, grove, ctx, manifest=manifest)
        main_match = _re.search(r'<main\b[^>]*>(.*?)</main>', html, _re.DOTALL)
        main_content = main_match.group(1).strip() if main_match else ""
        page_entry = {
            "title": post["title"],
            "main": main_content,
            "layout": post.get("layout") or grove["defaults"]["layout"],
        }
        toc_match = _re.search(
            r'<script type="application/json" id="toc-data">(.*?)</script>', html
        )
        if toc_match:
            import json as _json
            page_entry["toc"] = _json.loads(toc_match.group(1))
        pages[post["url_path"]] = page_entry

    # Render index page into memory
    posts_per_page = grove["defaults"]["posts_per_page"]
    index_html = render_index_page(index_posts[:posts_per_page], grove, ctx, manifest=manifest)
    index_main = _re.search(r'<main\b[^>]*>(.*?)</main>', index_html, _re.DOTALL)
    pages["/"] = {
        "title": grove["title"],
        "main": index_main.group(1).strip() if index_main else "",
        "layout": "index",
    }

    # Render archive into memory
    archive_html = render_archive_page(build_posts, grove, ctx, manifest=manifest)
    archive_main = _re.search(r'<main\b[^>]*>(.*?)</main>', archive_html, _re.DOTALL)
    pages["/archive/"] = {
        "title": f"Archive — {grove['title']}",
        "main": archive_main.group(1).strip() if archive_main else "",
        "layout": "archive",
    }

    # Generate indexes as data (not files)
    base_path = ctx["base_path"]
    first_load = generate_first_load_index_data(index_posts, posts_per_page, base_path=base_path)
    search_idx = generate_search_index_data(search_posts, base_path=base_path)

    # Collect and encrypt
    bundle_json = collect_bundle(pages, search_idx, first_load,
                                 asset_manifest=manifest, asset_salt=asset_salt)
    encryptor = make_encryptor(mnemonic)
    envelope_json = encryptor(bundle_json, {"title": grove["title"]})

    # Write gate page
    gate_html = render_gate_page(grove, ctx)
    (dist / "index.html").write_text(gate_html, encoding="utf-8")

    # Write encrypted bundle
    (dist / "bundle.enc").write_text(envelope_json, encoding="utf-8")

    # Encrypt asset files — enforcement by design: no plaintext in dist
    assets_dir = dist / "assets"
    if assets_dir.is_dir() and asset_encryptor:
        for path in sorted(assets_dir.rglob("*")):
            if path.is_file():
                enc_data = asset_encryptor(path.read_bytes())
                path.with_name(path.name + ".enc").write_text(enc_data, encoding="utf-8")
                path.unlink()

    # Copy renderer assets (CSS, JS, fonts)
    if corpus_root:
        shape_path = Path(corpus_root) / "shapes" / "grove"
    else:
        shape_path = Path(__file__).resolve().parent.parent
    if shape_path.is_dir():
        _copy_renderer_assets(dist, shape_path)

    _copy_favicon_files(dist, themes_dir, shape_path / "themes" if shape_path else None)
    _copy_theme_fonts(dist, themes_dir)
    _write_syntax_css(dist)

    # Stamp build hash into HTML footers and SW
    build_hash = _compute_build_hash(dist)
    _stamp_build_hash_in_html(dist, build_hash)

    if service_worker:
        _version_sw(dist, build_hash)
        # Encrypted grove: gate page is the only "page".
        # SPA root = '/' so the SW serves the gate page for all navigation
        # within scope (pushState URLs work on refresh).
        # OWNED_ASSETS intentionally empty — image paths in sw.js leak
        # content topics. Post-decryption image loading handled by
        # asset-decrypt.js on the client side.
        owned_pages = ['/']
        siblings = _collect_sibling_paths(corpus_root, ctx["base_url"])
        _inject_sw_declarations(dist, owned_pages, _GROVE_DYNAMIC_PATHS, [],
                                spa_roots=['/'], sibling_paths=siblings,
                                optional_static=_collect_optional_static(dist))
    elif (dist / 'sw.js').exists():
        _write_gravestone_sw(dist)

    return dist, mnemonic


def _build_local_first(grove_root: Path, grove: dict, ctx: dict,
                       build_posts: list, index_posts: list,
                       feed_posts: list, sitemap_posts: list,
                       search_posts: list, dist: Path, corpus_root,
                       themes_dir: Path,
                       *, manifest: dict | None = None,
                       service_worker: bool = True,
                       feature_endpoints: dict | None = None,
                       chat_config: dict | None = None) -> tuple:
    """Local-first build: content-addressed blobs, manifest, OG stubs, app shell.

    Renders all pages to memory, writes blobs and manifest instead of per-page HTML.
    OG stubs at canonical paths handle crawlers. App shell is the single index.html.
    """
    mnemonic_out = None

    # Render all content to memory
    pages, entries_meta = _collect_rendered_pages(
        build_posts, index_posts, grove, ctx, dist, manifest=manifest,
        grove_root=grove_root, feature_endpoints=feature_endpoints or {})

    # Priority assignment
    loading = grove.get("loading", {})
    priority_count = loading.get("priority_count", 5)
    assign_priorities(entries_meta, priority_count)

    # Write content-addressed blobs
    blobs_dir = dist / "blobs"
    blob_map = write_blobs(pages, blobs_dir)

    # Merge blob info into entries_meta
    for entry in entries_meta:
        route = entry["route"]
        if route in blob_map:
            entry["blob"] = blob_map[route]["blob"]
            entry["hash"] = blob_map[route]["hash"]

    # Build and write manifest
    loading_strategy = loading.get("strategy", "progressive")
    build_hash = "000000000000"  # placeholder, stamped after all files written
    manifest_assets = _manifest_assets_from_image_manifest(manifest) if manifest else []
    lf_manifest = build_manifest(
        entries=entries_meta,
        assets=manifest_assets,
        build_hash=build_hash,
        loading_strategy=loading_strategy,
        priority_count=priority_count,
    )

    # Write canonical path pages based on crawlable setting
    crawlable = ctx["crawlable"]
    if crawlable == "full":
        write_full_stubs(entries_meta, pages, dist, base_url=ctx["base_url"],
                         grove=grove, ctx=ctx,
                         chat_config=chat_config, feature_endpoints=feature_endpoints)
    elif crawlable == "thin":
        write_og_stubs(entries_meta, dist, base_url=ctx["base_url"],
                       grove=grove, ctx=ctx)
    # crawlable == "none": no stubs written

    # Write app shell as dist/index.html
    post_count = min(sum(1 for e in entries_meta if e["type"] == "post"), 24)
    shell_html = render_app_shell(grove, ctx, skeleton_count=post_count,
                                  chat_config=chat_config,
                                  feature_endpoints=feature_endpoints)
    (dist / "index.html").write_text(shell_html, encoding="utf-8")

    # 404.html = the app shell, so static hosts (GitHub Pages) serve it for
    # unmatched deep-links (/ghost/<slug>) and the SPA boots + client-routes.
    (dist / "404.html").write_text(
        render_app_shell(grove, ctx, skeleton_count=post_count,
                         chat_config=chat_config, feature_endpoints=feature_endpoints),
        encoding="utf-8")

    # Feeds, sitemap, redirects, search indexes — same as plain build
    _generate_feeds(feed_posts, grove, ctx, dist)
    _generate_sitemap(sitemap_posts, ctx, dist)
    _generate_redirects(build_posts, dist)
    _generate_search_indexes(index_posts, search_posts, grove, ctx, dist)

    # Renderer assets (CSS, JS, fonts)
    if corpus_root:
        shape_path = Path(corpus_root) / "shapes" / "grove"
    else:
        shape_path = Path(__file__).resolve().parent.parent
    if shape_path.is_dir():
        _copy_renderer_assets(dist, shape_path)

    _copy_favicon_files(dist, themes_dir, shape_path / "themes" if shape_path else None)
    _copy_theme_fonts(dist, themes_dir)
    _write_syntax_css(dist)

    # Compute real build hash and update manifest + HTML
    build_hash = _compute_build_hash(dist)
    lf_manifest["version"] = build_hash
    write_manifest(lf_manifest, dist)

    _stamp_build_hash_in_html(dist, build_hash)

    if service_worker:
        _version_sw(dist, build_hash)
        owned_pages = _collect_owned_pages(build_posts, dist)
        owned_assets = _collect_owned_assets(manifest) if manifest else []
        siblings = _collect_sibling_paths(corpus_root, ctx["base_url"])
        _inject_sw_declarations(dist, owned_pages, _GROVE_DYNAMIC_PATHS, owned_assets,
                                sibling_paths=siblings,
                                optional_static=_collect_optional_static(dist))
    elif (dist / 'sw.js').exists():
        _write_gravestone_sw(dist)

    return dist, mnemonic_out


def _collect_rendered_pages(build_posts: list[dict], index_posts: list[dict],
                            grove: dict, ctx: dict, dist: Path,
                            *, manifest=None,
                            grove_root: Path | None = None,
                            feature_endpoints: dict | None = None) -> tuple[dict[str, str], list[dict]]:
    """Render all content to memory instead of writing files.

    Returns (pages, entries_meta) where:
      pages: dict of route → HTML string
      entries_meta: list of dicts with route, type, title, excerpt, publish_date, section, tags, featured, og
    """
    pages = {}
    entries_meta = []

    # Posts — fragment content for blob storage (no page shell)
    for post in build_posts:
        html = render_post_fragment(post, grove, ctx, manifest=manifest)
        route = post["url_path"]
        pages[route] = html
        entries_meta.append({
            "route": route,
            "type": "post",
            "title": post.get("title", ""),
            "excerpt": post.get("excerpt", ""),
            "publish_date": post.get("publish_date", ""),
            "section": post.get("section", ""),
            "tags": post.get("tags", []),
            "featured": post.get("featured", False),
            "layout": post.get("layout") or grove["defaults"]["layout"],
            "theme": post.get("theme", ""),
            "og": {
                "title": post.get("title", ""),
                "description": post.get("excerpt", ""),
                "image": post.get("og", {}).get("image", "") if isinstance(post.get("og"), dict) else "",
            },
        })

    # Index page — fragment content
    posts_per_page = grove["defaults"]["posts_per_page"]
    index_html = render_index_fragment(index_posts[:posts_per_page], grove, ctx, manifest=manifest)
    pages["/"] = index_html
    entries_meta.append({
        "route": "/",
        "type": "index",
        "title": grove["title"],
        "layout": "index",
    })

    # Archive page — fragment content
    archive_html = render_archive_fragment(build_posts, grove, ctx)
    pages["/archive/"] = archive_html
    entries_meta.append({
        "route": "/archive/",
        "type": "archive",
        "title": f"Archive — {grove['title']}",
        "layout": "archive",
    })

    # Section indexes (auto-generated for subdirectories without explicit index.md)
    sections: dict[str, list[dict]] = {}
    section_has_explicit_index: set[str] = set()
    for post in build_posts:
        cp = post["content_path"]
        if post.get("is_section_index"):
            section_has_explicit_index.add(cp)
        elif "/" in cp:
            section = cp.split("/")[0]
            sections.setdefault(section, []).append(post)

    for section, section_posts in sections.items():
        if section in section_has_explicit_index:
            continue
        section_title = section.replace("-", " ").title()
        section_html = render_index_fragment(section_posts, grove, ctx, page_title=section_title, manifest=manifest)
        route = f"/{section}/"
        pages[route] = section_html
        entries_meta.append({
            "route": route,
            "type": "section_index",
            "title": section_title,
            "layout": "index",
        })

    # Declared pages (the pages: map) — chat pages live here. The local-first path
    # must emit them just like posts; dropping them is the bug this fixes.
    if grove_root is not None:
        for page in load_pages(grove_root, grove):
            body_html, _hashes = compose_fragment(page, grove, ctx, grove_root=grove_root,
                                                  posts=build_posts,
                                                  feature_endpoints=feature_endpoints or {})
            route = page["route"]
            pages[route] = body_html
            entries_meta.append({
                "route": route,
                "type": "page",
                "title": page.get("title", ""),
                "layout": page.get("layout") or grove["defaults"]["layout"],
                "og": {
                    "title": page.get("title", ""),
                    "description": page.get("og", {}).get("description", "") if isinstance(page.get("og"), dict) else "",
                    "image": page.get("og", {}).get("image", "") if isinstance(page.get("og"), dict) else "",
                },
            })

    return pages, entries_meta


def build(grove_root: Path, corpus_root: Path | None = None, *, base_url: str,
          encrypted: bool = False, mnemonic: str = None, rotate: bool = False,
          service_worker: bool = True, drafts: bool = False,
          local_first: bool = False, on_clear: str = "reload",
          crawlable: str, feature_endpoints: dict | None = None,
          chat_config: dict | None = None) -> tuple:
    """Build a grove from source to .corpus/shapes/grove/builds/. Returns (dist, mnemonic_out).

    base_url is injected at build time — it comes from the active deploy target
    or from the dev server. Never stored in grove.yaml, never defaulted here.
    The build pipeline refuses to produce output without a canonical URL.
    """
    grove_root = Path(grove_root)
    feature_endpoints = feature_endpoints or {}

    grove = _load_grove(grove_root)
    _validate_features(grove.get("features", []))

    # Fail loud: a grove with chat features requires chat_config at build time so the
    # static pages carry the chat-config island. Without it the deployed chat is broken
    # in a way that only surfaces at runtime (no endpoint → silent failure).
    _has_chat = any(f.get("type") == "chat" for f in grove.get("features", []))
    if _has_chat and chat_config is None:
        raise BuildError("grove declares chat feature(s) but no chat_config was resolved")

    # Resolve themes — path relative to grove_root, or shape default
    theme_ref = grove.get("theme")
    if theme_ref:
        themes_dir = (grove_root / theme_ref).resolve()
        if not themes_dir.is_dir():
            raise BuildError(
                f"Theme directory not found: {themes_dir} "
                f"(resolved from '{theme_ref}' relative to {grove_root})"
            )
    else:
        themes_dir = Path(__file__).resolve().parent.parent / "themes"
        if corpus_root:
            themes_dir = Path(corpus_root) / "shapes" / "grove" / "themes"
    ctx = _build_ctx(base_url, themes_dir, on_clear=on_clear, crawlable=crawlable,
                     features=grove.get("features", []))
    ctx["_grove_root"] = grove_root  # composer needs it to find elements/<name>/

    posts = _resolve_posts(grove_root)

    if drafts:
        build_posts = filter_for_serve_build(posts)
        index_posts = filter_for_serve_index(posts)
        feed_posts = []
        sitemap_posts = []
        search_posts = filter_for_serve_index(posts)
    else:
        build_posts = filter_for_build(posts)
        index_posts = filter_for_index(posts)
        feed_posts = filter_for_feed(posts)
        sitemap_posts = filter_for_sitemap(posts)
        search_posts = filter_for_search(posts)

    if corpus_root:
        dist = derive_build_path(grove_root, Path(corpus_root))
    else:
        # Direct invocation without corpus (tests, standalone)
        dist = grove_root / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)

    _copy_grove_assets(grove_root, dist)

    # Image processing — generate responsive variants
    assets_dir = grove_root / "assets"
    manifest = {}
    if assets_dir.is_dir():
        manifest = process_images(assets_dir, dist, build_posts)

    if encrypted:
        return _build_encrypted(grove_root, grove, ctx, posts, build_posts, dist,
                                corpus_root, themes_dir, mnemonic=mnemonic, rotate=rotate,
                                manifest=manifest, service_worker=service_worker)

    if local_first:
        return _build_local_first(grove_root, grove, ctx, build_posts, index_posts,
                                  feed_posts, sitemap_posts, search_posts, dist,
                                  corpus_root, themes_dir, manifest=manifest,
                                  service_worker=service_worker,
                                  feature_endpoints=feature_endpoints,
                                  chat_config=chat_config)

    # Plain build proceeds here.
    mnemonic_out = None

    _render_posts(build_posts, grove, ctx, dist, manifest=manifest)
    pages = load_pages(grove_root, grove)
    _assert_no_page_post_collision(pages, build_posts)
    if not any(p["route"] == "/" for p in pages):
        _render_default_home(grove, ctx, dist, index_posts, manifest=manifest)
    _render_pages(pages, grove, ctx, dist, index_posts, feature_endpoints=feature_endpoints,
                  chat_config=chat_config, manifest=manifest)
    _render_section_indexes(build_posts, grove, ctx, dist, manifest=manifest)
    _render_collections(grove_root, build_posts, grove, ctx, dist, manifest=manifest)
    _render_archive(build_posts, grove, ctx, dist, manifest=manifest)
    _generate_feeds(feed_posts, grove, ctx, dist)
    _generate_sitemap(sitemap_posts, ctx, dist)
    _generate_redirects(build_posts, dist)
    _generate_search_indexes(index_posts, search_posts, grove, ctx, dist)

    # Derive shape path from this module's location; used for asset copy
    if corpus_root:
        shape_path = Path(corpus_root) / "shapes" / "grove"
    else:
        # This file lives at shapes/grove/exporters/build.py
        shape_path = Path(__file__).resolve().parent.parent
    if shape_path.is_dir():
        _copy_renderer_assets(dist, shape_path)

    _copy_favicon_files(dist, themes_dir, shape_path / "themes" if shape_path else None)
    _copy_theme_fonts(dist, themes_dir)
    _write_syntax_css(dist)

    # Stamp build hash into HTML footers and SW
    build_hash = _compute_build_hash(dist)
    _stamp_build_hash_in_html(dist, build_hash)

    if service_worker:
        _version_sw(dist, build_hash)
        owned_pages = _collect_owned_pages(build_posts, dist)
        owned_assets = _collect_owned_assets(manifest) if manifest else []
        siblings = _collect_sibling_paths(corpus_root, ctx["base_url"])
        spa_roots = _collect_chat_spa_roots(pages, grove)
        _inject_sw_declarations(dist, owned_pages, _GROVE_DYNAMIC_PATHS, owned_assets,
                                spa_roots=spa_roots, sibling_paths=siblings,
                                optional_static=_collect_optional_static(dist))
    elif (dist / 'sw.js').exists():
        _write_gravestone_sw(dist)

    return dist, mnemonic_out
