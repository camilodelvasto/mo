"""Grove dev server — build, serve static files, watch, SSE live-reload.

Endpoints:
    GET /           → dist/index.html
    GET /events     → SSE stream (sends "reload" on file changes)
    GET /<path>     → static files from dist/ (try_files: path, path/index.html)
                      then renderer/core/ (CSS, JS, static assets)
"""
from __future__ import annotations

import mimetypes
import sys
import threading
import time
from html import escape
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Exporters live two levels up from this file.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'exporters'))

from build import build, BuildError, _load_grove, _resolve_posts, _build_ctx  # noqa: E402
from pages import load_pages  # noqa: E402
from shapes.grove.exporters.chat_config import chat_presentation, emit_chat_config  # noqa: E402
from cli.infra.origin import origin_of  # noqa: E402


DEFAULT_PORT = 4200
MAX_PORT_ATTEMPTS = 10

_HMR_SCRIPT = """\
<script>(function() {
  var handlers = {
    content: function() {
      var scrollY = window.scrollY;
      fetch(location.href, {cache: 'no-store'}).then(function(r) { return r.text(); }).then(function(html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var newMain = doc.getElementById('main');
        if (newMain) {
          document.getElementById('main').replaceWith(newMain);
          window.scrollTo(0, scrollY);
        }
        var newTitle = doc.querySelector('title');
        if (newTitle) document.title = newTitle.textContent;
        var oldToc = document.getElementById('toc-data');
        var newToc = doc.getElementById('toc-data');
        if (oldToc && newToc) oldToc.replaceWith(newToc);
        else if (newToc) document.body.appendChild(newToc);
        else if (oldToc) oldToc.remove();
      });
    },
    config: function() { location.reload(); }
  };
  var es = new EventSource('/events');
  es.onmessage = function(e) {
    var handler = handlers[e.data];
    if (!handler) throw new Error('Unknown HMR event: ' + e.data);
    handler();
  };
})()</script>"""


def inject_hmr_script(html: str) -> str:
    """Inject live-reload script before </body>. No-op if no </body> tag."""
    tag = '</body>'
    idx = html.lower().find(tag)
    if idx == -1:
        return html
    return html[:idx] + _HMR_SCRIPT + '\n' + html[idx:]


def pages_by_route(pages):
    """Map normalized (trailing-slash) route -> page dict."""
    out = {}
    for page in pages:
        route = page["route"]
        if route != "/" and not route.endswith("/"):
            route += "/"
        out[route] = page
    return out


class GroveHandler(BaseHTTPRequestHandler):

    # HTTP/1.0 = no keep-alive. Each response closes the connection and frees
    # the thread. HTTP/1.1 keep-alive causes threads to block on readline()
    # forever after MPA navigation, exhausting Chrome's 6-connection-per-origin
    # limit within 2-3 page transitions.
    protocol_version = 'HTTP/1.0'

    dist_path: Path = None
    shape_path: Path = None
    corpus_root: Path = None
    sse_clients: list = []
    lock: threading.Lock = None
    grove_root: Path = None
    grove: dict = None
    ctx: dict = None
    build_posts: list = None
    index_posts: list = None
    app_shell_html: str = None
    chat_config: dict = None
    image_manifest: dict = None
    pages_by_route: dict = None

    def log_message(self, format, *args):
        pass

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]

        if path == '/events':
            self._serve_sse()
            return

        if path.startswith('/_dev/content'):
            self._serve_dev_content(self.path)
            return

        if path.startswith('/theme/'):
            self._serve_theme_file(path)
            return

        # Resolve static file from dist
        rel = path.lstrip('/')
        if not rel or '.' not in rel.split('/')[-1]:
            self._serve_app_shell(path)
            return

        self._serve_static(rel)

    def _serve_static(self, rel_path):
        # Path traversal protection
        if '..' in rel_path:
            self._error(403, 'Forbidden')
            return

        dist = self.dist_path
        candidate = (dist / rel_path).resolve()

        # Verify resolved path stays under dist
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            self._error(403, 'Forbidden')
            return

        # try_files: dist exact, dist/index.html, then renderer/core/
        if candidate.is_file():
            self._serve_file(candidate)
        elif (candidate / 'index.html').is_file():
            self._serve_file(candidate / 'index.html')
        else:
            self._serve_from_renderer(rel_path)

    def _serve_file(self, file_path: Path):
        content_type = mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'
        body = file_path.read_bytes()

        # Inject HMR script into HTML responses
        if content_type == 'text/html':
            body = inject_hmr_script(body.decode('utf-8')).encode('utf-8')

        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(body))
        # Dev server: no caching. Ensures HMR content swap fetches fresh HTML.
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _serve_from_renderer(self, rel_path):
        """Fall through to renderer/core/ then renderer/ for static assets.

        Core assets (style.css, app.js) live in renderer/core/.
        Shell assets (shell-web/transport.js) live in renderer/shell-web/.
        Dynamic imports resolve relative paths like ../shell-web/transport.js
        to /shell-web/transport.js in the browser.
        """
        renderer = self.shape_path / 'renderer'
        # Try renderer/core/ first (where CSS, JS, HTML live)
        core = renderer / 'core'
        candidate = (core / rel_path).resolve()
        try:
            candidate.relative_to(core.resolve())
            if candidate.is_file():
                self._serve_file(candidate)
                return
        except ValueError:
            pass
        # Then try renderer/ root (for shell-web/, shell-tauri/ imports)
        candidate = (renderer / rel_path).resolve()
        try:
            candidate.relative_to(renderer.resolve())
            if candidate.is_file():
                self._serve_file(candidate)
                return
        except ValueError:
            pass
        # Then try themes/default/ (dark.css, theme overrides)
        themes = self.shape_path / 'themes' / 'default'
        candidate = (themes / rel_path).resolve()
        try:
            candidate.relative_to(themes.resolve())
        except ValueError:
            self._error(403, 'Forbidden')
            return
        if candidate.is_file():
            self._serve_file(candidate)
        else:
            self._error(404, f'Not found: {rel_path}')

    def _serve_theme_file(self, path):
        filename = path.split('/')[-1]
        grove = _load_grove(self.grove_root)
        theme_ref = grove.get("theme")
        if not theme_ref:
            self._error(404, 'No theme field in grove.yaml')
            return
        themes_dir = (self.grove_root / theme_ref).resolve()
        default_theme = themes_dir / "default"
        if not default_theme.is_dir():
            self._error(404, f'Default theme not found in {themes_dir}')
            return
        file_path = default_theme / filename
        if not file_path.exists():
            self._error(404, f'Not found: {filename}')
            return
        self._serve_file(file_path)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        # MPA: only one page is active at a time. Kill all previous SSE
        # connections — their TCP sockets are zombie (writes succeed into
        # kernel buffer but the browser is gone).
        with self.lock:
            for old in self.sse_clients:
                try:
                    old.close()
                except OSError:
                    pass
            self.sse_clients.clear()
            self.sse_clients.append(self.wfile)
        try:
            while True:
                time.sleep(0.25)
                try:
                    self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
                except (OSError, ValueError):
                    break
        finally:
            with self.lock:
                if self.wfile in self.sse_clients:
                    self.sse_clients.remove(self.wfile)

    def _serve_app_shell(self, path=None):
        """Serve the app shell with dev environment flag injected."""
        html = self.app_shell_html or ''
        # Reflect the matched composed page's layout/width on the body so a dev cold load
        # styles correctly. The dev SPA otherwise leaves data-layout="index" for every route
        # (no manifest → no onBeforeNavigate), so per-page layout/width would never apply.
        page = self._page_for_route(path) if path else None
        if page is not None:
            layout = page.get("layout") or "page"
            width = page.get("width", "content")
            html = html.replace(
                '<body data-layout="index">',
                f'<body data-layout="{escape(layout)}" data-width="{escape(width)}">', 1)
        # Render the route's REAL content into #main instead of the skeleton placeholder,
        # so the initial dev paint matches the static build (no skeleton->content jump that
        # shifts the footer). Falls back to the skeleton if the route has no fragment.
        if path:
            route = path if (path == '/' or path.endswith('/')) else path + '/'
            fragment = self._render_fragment(route)
            if fragment is not None:
                import re
                html = re.sub(r'<main id="main">.*?</main>',
                              lambda _m: f'<main id="main">{fragment}</main>',
                              html, count=1, flags=re.DOTALL)
        # Inject dev env meta tag so app.js uses dev transport
        html = html.replace(
            '<meta name="grove-base-path"',
            '<meta name="grove-env" content="dev">\n    <meta name="grove-base-path"'
        )
        if self.chat_config:
            html = html.replace(
                '</head>',
                emit_chat_config(self.grove, self.pages_by_route.values(), self.ctx,
                                 endpoint=self.chat_config["endpoint"],
                                 gate=self.chat_config["gate"]) + '</head>')
        html = html.replace('__BUILD_HASH__', 'dev')
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', len(body))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _serve_dev_content(self, full_path):
        """Render a single route as a <main> fragment and return as JSON."""
        import json as _json
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(full_path)
        params = parse_qs(parsed.query)
        route = params.get('route', [''])[0]
        if not route:
            self._error(400, 'Missing route parameter')
            return
        if not route.startswith('/'):
            route = '/' + route
        if not route.endswith('/') and route != '/':
            route += '/'

        html = self._render_fragment(route)
        if html is None:
            self._error(404, f'Route not found: {route}')
            return

        layout, width = self._meta_for_route(route)
        body = _json.dumps({'html': html, 'layout': layout, 'width': width},
                           ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _feature_endpoints(self):
        if not self.chat_config:
            return {}
        return {f["id"]: origin_of(self.chat_config["endpoint"])
                for f in self.grove.get("features", [])
                if f.get("type") == "chat"}

    def _page_for_route(self, route):
        """The composed page that owns a route: an exact `pages:` entry, or a `mount:
        subtree` page whose prefix the route falls under (the page owns the subtree; the
        router never parses the slug). Returns the page record or None."""
        if not route or not self.pages_by_route:
            return None
        if route != "/" and not route.endswith("/"):
            route += "/"
        page = self.pages_by_route.get(route)
        if page is not None:
            return page
        for p in self.pages_by_route.values():
            if p.get("mount") == "subtree":
                base = p["route"].rstrip("/") + "/"
                if route != base and route.startswith(base):
                    return p
        return None

    def _render_fragment(self, route):
        """Render a <main> fragment for a single route using in-memory grove state."""
        from render import render_post_fragment, render_index_fragment, render_archive_fragment
        grove, ctx = self.grove, self.ctx
        if not grove or not ctx:
            return None

        # Pages map takes priority — any route declared as a page (including home).
        if self.pages_by_route:
            page = self._page_for_route(route)
            if page is not None:
                from compose import compose_fragment
                ctx = {**self.ctx, "_grove_root": self.grove_root}
                # compose_fragment returns (html, script_hashes). Script hashes are
                # dropped here: inline scripts inserted via innerHTML don't execute,
                # so authored scripts only run on full-page loads via compose_page.
                # Batch-1 limitation — SPA navigation skips authored element scripts.
                html, _ = compose_fragment(page, self.grove, ctx, grove_root=self.grove_root,
                                           posts=self.index_posts,
                                           feature_endpoints=self._feature_endpoints())
                return html

        # Default bare-grove feed home — only when no pages entry owns '/'.
        if route == '/':
            posts_per_page = grove["defaults"]["posts_per_page"]
            return render_index_fragment(self.index_posts[:posts_per_page], grove, ctx)

        if route == '/archive/':
            return render_archive_fragment(self.build_posts, grove, ctx)

        # Individual post
        for post in self.build_posts:
            if post.get("url_path") == route:
                return render_post_fragment(post, grove, ctx, manifest=self.image_manifest)

        # Section indexes
        sections = {}
        for post in self.build_posts:
            cp = post["content_path"]
            if "/" in cp and not post.get("is_section_index"):
                section = cp.split("/")[0]
                sections.setdefault(section, []).append(post)
        section_name = route.strip("/")
        if section_name in sections:
            section_title = section_name.replace("-", " ").title()
            return render_index_fragment(sections[section_name], grove, ctx, page_title=section_title)

        return None

    def _meta_for_route(self, route):
        """The (layout, width) for a route — mirrors _render_fragment's branching so the
        dev SPA can set body data-layout/width on navigation. Prod gets this from the
        manifest via onBeforeNavigate; dev has no manifest, so it rides with the fragment.
        Layout decides chrome; width is 'full' only under app (which owns the frame)."""
        grove = self.grove
        if self.pages_by_route:
            page = self._page_for_route(route)
            if page is not None:
                layout = page.get("layout") or "page"
                width = "full" if layout == "app" else page.get("width", "content")
                return layout, width
        if route == '/':
            return "index", "content"
        if route == '/archive/':
            return "archive", "content"
        for post in self.build_posts:
            if post.get("url_path") == route:
                return (post.get("layout") or grove["defaults"]["layout"]), "content"
        return "index", "content"   # section indexes (and any matched fallback)

    def _error(self, code, msg):
        body = msg.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)


def broadcast_event(sse_clients, lock, event_type):
    """Send typed event to all connected SSE clients.

    event_type must be a known HMR event: 'content' or 'config'.
    """
    payload = f'data: {event_type}\n\n'.encode()
    with lock:
        dead = []
        for client in sse_clients:
            try:
                client.write(payload)
                client.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                dead.append(client)
        for d in dead:
            sse_clients.remove(d)


def _classify_change(path, grove_root):
    """Classify a changed file path into an HMR event type.

    Returns 'content' for post/asset changes, 'config' for grove.yaml.
    """
    if path == grove_root / 'grove.yaml':
        return 'config'
    return 'content'


def watch_and_rebuild(grove_root, dist_ref, clients, lock, *, base_url, interval=0.5, corpus_root=None):
    """Watch grove source files, rebuild on change, broadcast typed event.

    dist_ref is a single-element list holding the current dist Path,
    mutated in-place so the handler picks up the new dist.
    """
    watch_paths = [
        grove_root / 'posts',
        grove_root / 'grove.yaml',
        grove_root / 'pages',
        grove_root / 'elements',
    ]

    mtimes = {}
    for p in watch_paths:
        if p.is_file():
            mtimes[p] = p.stat().st_mtime
        elif p.is_dir():
            for f in p.rglob('*'):
                if f.is_file():
                    mtimes[f] = f.stat().st_mtime

    while True:
        time.sleep(interval)
        changed_files = []
        current = {}
        for p in watch_paths:
            if p.is_file():
                current[p] = None
            elif p.is_dir():
                for f in p.rglob('*'):
                    if f.is_file():
                        current[f] = None
        for f in current:
            try:
                mt = f.stat().st_mtime
            except FileNotFoundError:
                continue
            if f not in mtimes or mtimes[f] != mt:
                mtimes[f] = mt
                changed_files.append(f)

        if changed_files:
            try:
                new_dist, _ = _dev_build(grove_root, corpus_root, base_url=base_url,
                                         chat_config=GroveHandler.chat_config)
                dist_ref[0] = new_dist
                GroveHandler.dist_path = new_dist
            except BuildError as e:
                print(f'\033[31mBuild error:\033[0m {e}')
            try:
                grove, ctx, build_posts, index_posts, app_shell_html, image_manifest, pbr = \
                    _load_dev_state(grove_root, corpus_root, base_url)
                GroveHandler.grove = grove
                GroveHandler.ctx = ctx
                GroveHandler.build_posts = build_posts
                GroveHandler.index_posts = index_posts
                GroveHandler.app_shell_html = app_shell_html
                GroveHandler.image_manifest = image_manifest
                GroveHandler.pages_by_route = pbr
            except Exception as e:
                print(f'\033[31mDev state error:\033[0m {e}')
            # Config change wins — if grove.yaml changed alongside content,
            # the whole page structure may have shifted.
            types = {_classify_change(f, grove_root) for f in changed_files}
            event_type = 'config' if 'config' in types else 'content'
            broadcast_event(clients, lock, event_type)


def _bind_server(handler_class, start_port, max_attempts):
    """Try start_port through start_port + max_attempts - 1 until one binds."""
    for offset in range(max_attempts):
        port = start_port + offset
        try:
            srv = ThreadingHTTPServer(('127.0.0.1', port), handler_class)
            return srv
        except OSError as e:
            if e.errno == 48 and offset < max_attempts - 1:  # Address in use
                continue
            raise


def _load_dev_state(grove_root, corpus_root, base_url):
    """Load grove config, resolve posts, build render context for dev."""
    grove = _load_grove(grove_root)
    posts = _resolve_posts(grove_root)

    theme_ref = grove.get("theme")
    if theme_ref:
        themes_dir = (grove_root / theme_ref).resolve()
        if not themes_dir.is_dir():
            raise Exception(f"Theme directory not found: {themes_dir}")
    else:
        themes_dir = Path(__file__).resolve().parent.parent / 'themes'
        if corpus_root:
            themes_dir = Path(corpus_root) / 'shapes' / 'grove' / 'themes'

    ctx = _build_ctx(base_url, themes_dir, on_clear="reload", crawlable="none",
                     features=grove.get("features", []))

    from visibility import filter_for_serve_build, filter_for_serve_index
    build_posts = filter_for_serve_build(posts)
    index_posts = filter_for_serve_index(posts)

    from app_shell import render_app_shell
    app_shell_html = render_app_shell(grove, ctx)

    # Image manifest for dev fragment rendering — reads cached variants from dist
    from images import process_images
    assets_dir = grove_root / 'assets'
    image_manifest = {}
    dist_path = GroveHandler.dist_path
    if assets_dir.is_dir() and dist_path:
        image_manifest = process_images(assets_dir, dist_path, build_posts)

    grove_pages = load_pages(grove_root, grove)
    pbr = pages_by_route(grove_pages)

    return grove, ctx, build_posts, index_posts, app_shell_html, image_manifest, pbr


def _dev_build(grove_root, corpus_root, *, base_url, chat_config):
    """Single build path for dev — initial and watcher both call this so the
    chat-config island never drifts between first paint and hot-rebuild."""
    grove = _load_grove(grove_root)
    feature_endpoints = ({f["id"]: origin_of(chat_config["endpoint"])
                          for f in grove.get("features", []) if f.get("type") == "chat"}
                         if chat_config else {})
    return build(grove_root, corpus_root, base_url=base_url, drafts=True, crawlable="none",
                 feature_endpoints=feature_endpoints, chat_config=chat_config)


def serve_grove(grove_root: Path, shape_path: Path, port: int = DEFAULT_PORT,
                corpus_root: Path | None = None, chat_config: dict | None = None):
    """Build, serve, and watch a grove."""
    grove_root = Path(grove_root)

    # Dev server injects its own base_url — never read from grove.yaml
    dev_base_url = f"http://localhost:{port}"

    # Load grove.yaml up front to fail fast: a declared chat feature has nowhere to
    # talk without a resolved chat_config. _dev_build / _load_dev_state reload it
    # internally — that duplication is acceptable; grove.yaml is tiny and this keeps
    # serve_grove's startup sequence explicit.
    _grove_pre = _load_grove(grove_root)
    has_chat = any(f.get("type") == "chat" for f in _grove_pre.get("features", []))
    if has_chat and chat_config is None:
        raise SystemExit(
            "this grove declares a chat feature; pass --chat-endpoint <url> or "
            "--env <env> to `mo grove serve` (default env is 'local')")

    # Initial build — same path the watcher uses, so first paint and hot-rebuild agree.
    dist, _ = _dev_build(grove_root, corpus_root, base_url=dev_base_url, chat_config=chat_config)
    GroveHandler.dist_path = dist

    grove, ctx, build_posts, index_posts, app_shell_html, image_manifest, pbr = \
        _load_dev_state(grove_root, corpus_root, dev_base_url)

    sse_clients = []
    lock = threading.Lock()
    GroveHandler.shape_path = shape_path
    GroveHandler.corpus_root = corpus_root
    GroveHandler.sse_clients = sse_clients
    GroveHandler.lock = lock
    GroveHandler.grove_root = grove_root
    GroveHandler.grove = grove
    GroveHandler.ctx = ctx
    GroveHandler.build_posts = build_posts
    GroveHandler.index_posts = index_posts
    GroveHandler.app_shell_html = app_shell_html
    GroveHandler.chat_config = chat_config
    GroveHandler.image_manifest = image_manifest
    GroveHandler.pages_by_route = pbr

    server = _bind_server(GroveHandler, port, MAX_PORT_ATTEMPTS)
    actual_port = server.server_address[1]

    # Start watcher
    dist_ref = [dist]
    watcher = threading.Thread(
        target=watch_and_rebuild,
        args=(grove_root, dist_ref, sse_clients, lock),
        kwargs={'corpus_root': corpus_root, 'base_url': dev_base_url},
        daemon=True,
    )
    watcher.start()

    # ANSI formatting
    bold = '\033[1m'
    dim = '\033[2m'
    cyan = '\033[36m'
    reset = '\033[0m'

    print()
    print(f'{bold}Grove dev server{reset}')
    print(f'  → {cyan}http://localhost:{actual_port}{reset}')
    print(f'  {dim}Root: {grove_root.resolve()}{reset}')
    print(f'  {dim}Dist: {dist.resolve()}{reset}')
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped')
        server.server_close()


def serve(content_path: Path, shape_path: Path, corpus_root: Path,
          chat_config: dict | None = None) -> None:
    """CLI contract: mo grove serve <path>. content_path is the grove root."""
    serve_grove(content_path, shape_path, corpus_root=corpus_root, chat_config=chat_config)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: server.py <grove_root> [port]')
        sys.exit(1)
    root = Path(sys.argv[1])
    p = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT
    serve_grove(root, p)
