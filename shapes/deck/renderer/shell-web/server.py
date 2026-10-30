#!/usr/bin/env python3
"""Deck HTTP server — serves content, theme, static files, and SSE reload events.

Endpoints:
    GET /                → renderer/core/index.html
    GET /content         → content YAML serialized as JSON
    GET /theme           → resolved theme tokens as JSON
    GET /events          → SSE stream (sends "reload" on file changes)
    GET /data/<path>     → files from corpus root (path traversal protected)
    GET /fonts/<path>    → font files from shape fonts/
    GET /fonts/fonts.css → @font-face CSS for all bundled fonts
    GET /vendor/<path>   → vendored JS from renderer/core/vendor/
    GET /<path>          → static files from renderer/core/
"""
from __future__ import annotations

import datetime
import json
import mimetypes
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import yaml

from cli.resolver import resolve_theme_dir
from cli.fonts import parse_font_filename, build_fonts_css
from cli.component_resolver import resolve_component

_FONTS_CSS_CACHE = None


def _check_token_collisions(data: dict) -> list[str]:
    gradients = set(data.get('gradients', {}).keys())
    palette = set(data.get('palette', {}).keys())
    borders = set(data.get('borders', {}).keys())
    collisions = []
    for name in gradients & palette:
        collisions.append(f'"{name}" in both gradients and palette')
    for name in gradients & borders:
        collisions.append(f'"{name}" in both gradients and borders')
    for name in palette & borders:
        collisions.append(f'"{name}" in both palette and borders')
    return collisions


def _json_default(obj):
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')


class DeckHandler(BaseHTTPRequestHandler):

    content_path: Path = None
    shape_path: Path = None
    corpus_root: Path = None
    theme_dir: Path = None
    sse_clients: list = []
    lock: threading.Lock = None

    def log_message(self, format, *args):
        pass

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_HEAD(self):
        path = self.path.split('?')[0]
        if path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', '0')
            self.end_headers()
        else:
            self.send_response(405)
            self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]

        if path == '/':
            self._serve_file(self.shape_path / 'renderer' / 'core' / 'index.html', 'text/html')
        elif path in ('/content', '/content.json'):
            self._serve_json(yaml.safe_load(self.content_path.read_text()))
        elif path in ('/theme', '/theme/tokens.json'):
            tokens_path = self.theme_dir / 'tokens.yaml'
            if not tokens_path.exists():
                self._error(404, f'tokens.yaml not found in {self.theme_dir}')
                return
            data = yaml.safe_load(tokens_path.read_text())
            collisions = _check_token_collisions(data)
            if collisions:
                self._error(500, f"Theme token collision: {'; '.join(collisions)}")
                return
            self._serve_json(data)
        elif path == '/theme/style.css':
            css_path = self.theme_dir / 'style.css'
            if not css_path.exists():
                self._error(404, 'style.css not found')
                return
            self._serve_file(css_path, 'text/css')
        elif path.startswith('/theme/'):
            filename = path.split('/')[-1]
            file_path = self.theme_dir / filename
            if not file_path.exists():
                self._error(404, f'Not found: {filename}')
                return
            self._serve_file(file_path)
        elif path == '/events':
            self._serve_sse()
        elif path.startswith('/components/'):
            self._serve_component(path)
        elif path.startswith('/data/'):
            self._serve_data(path[6:])
        elif path == '/fonts/fonts.css':
            self._serve_fonts_css()
        elif path.startswith('/fonts/'):
            self._serve_from(self.shape_path / 'fonts', path[7:])
        elif path.startswith('/vendor/'):
            self._serve_from(self.shape_path / 'renderer' / 'core' / 'vendor', path[8:])
        else:
            self._serve_from(self.shape_path / 'renderer' / 'core', path.lstrip('/'))

    def _serve_json(self, data):
        body = json.dumps(data, default=_json_default).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, file_path, content_type=None):
        if not file_path.exists():
            self._error(404, f'Not found: {file_path.name}')
            return
        if not content_type:
            content_type = mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_from(self, base_dir, rel_path):
        if '..' in rel_path or rel_path.startswith('/'):
            self._error(403, 'Forbidden')
            return
        full = (base_dir / rel_path).resolve()
        try:
            full.relative_to(base_dir.resolve())
        except ValueError:
            self._error(403, 'Forbidden')
            return
        self._serve_file(full)

    def _serve_fonts_css(self):
        global _FONTS_CSS_CACHE
        if _FONTS_CSS_CACHE is None:
            _FONTS_CSS_CACHE = build_fonts_css(self.shape_path / 'fonts').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/css')
        self.send_header('Content-Length', len(_FONTS_CSS_CACHE))
        self.end_headers()
        self.wfile.write(_FONTS_CSS_CACHE)

    def _serve_component(self, path):
        # /components/<name>/<file>
        parts = path.strip('/').split('/')
        if len(parts) != 3:
            self._error(404, f'Invalid component path: {path}')
            return
        _, comp_name, filename = parts
        if filename not in ('render.js', 'style.css'):
            self._error(404, f'Only render.js and style.css are served for components')
            return
        try:
            comp_dir = resolve_component(
                comp_name, corpus_root=self.corpus_root, shape_path=self.shape_path,
            )
        except FileNotFoundError as e:
            self._error(404, str(e))
            return
        file_path = comp_dir / filename
        if not file_path.exists():
            self._error(404, f'Component file not found: {filename}')
            return
        content_type = 'application/javascript' if filename.endswith('.js') else 'text/css'
        self._serve_file(file_path, content_type)

    def _serve_data(self, rel_path):
        if '..' in rel_path or rel_path.startswith('/'):
            self._error(403, 'Path traversal blocked')
            return
        full = (self.corpus_root / rel_path).resolve()
        try:
            full.relative_to(self.corpus_root.resolve())
        except ValueError:
            self._error(403, 'Path traversal blocked')
            return
        self._serve_file(full)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        with self.lock:
            self.sse_clients.append(self.wfile)
        try:
            while True:
                time.sleep(1)
                try:
                    self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
        finally:
            with self.lock:
                if self.wfile in self.sse_clients:
                    self.sse_clients.remove(self.wfile)

    def _error(self, code, msg):
        body = msg.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)


def broadcast_reload(sse_clients, lock):
    with lock:
        dead = []
        for client in sse_clients:
            try:
                client.write(b'data: reload\n\n')
                client.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                dead.append(client)
        for d in dead:
            sse_clients.remove(d)


def watch_files(paths, sse_clients, lock, interval=0.5):
    mtimes = {}
    for p in paths:
        if p.is_file():
            mtimes[p] = p.stat().st_mtime
        elif p.is_dir():
            for f in p.rglob('*'):
                if f.is_file():
                    mtimes[f] = f.stat().st_mtime

    while True:
        time.sleep(interval)
        changed = False
        current = {}
        for p in paths:
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
                changed = True
        if changed:
            broadcast_reload(sse_clients, lock)


DEFAULT_PORT = 4100
MAX_PORT_ATTEMPTS = 10


def _bind_server(handler_class, start_port, max_attempts):
    """Try start_port, start_port+1, ... until one binds."""
    import socket
    for offset in range(max_attempts):
        port = start_port + offset
        try:
            srv = ThreadingHTTPServer(('127.0.0.1', port), handler_class)
            return srv
        except OSError as e:
            if e.errno == 48 and offset < max_attempts - 1:  # Address in use
                continue
            raise


def serve(content_path: Path, shape_path: Path, corpus_root: Path, port: int = DEFAULT_PORT):
    content_data = yaml.safe_load(content_path.read_text())
    theme_ref = content_data.get('theme')
    if not theme_ref:
        raise ValueError(f'No theme field in {content_path} — run moui check first')

    theme_dir = resolve_theme_dir(theme_ref, content_path)

    sse_clients = []
    lock = threading.Lock()

    DeckHandler.content_path = content_path
    DeckHandler.shape_path = shape_path
    DeckHandler.corpus_root = corpus_root
    DeckHandler.theme_dir = theme_dir
    DeckHandler.sse_clients = sse_clients
    DeckHandler.lock = lock

    server = _bind_server(DeckHandler, port, MAX_PORT_ATTEMPTS)
    actual_port = server.server_address[1]

    watch_paths = [
        content_path,
        theme_dir,
    ]
    watcher = threading.Thread(target=watch_files, args=(watch_paths, sse_clients, lock), daemon=True)
    watcher.start()

    # ANSI formatting
    bold = '\033[1m'
    dim = '\033[2m'
    cyan = '\033[36m'
    reset = '\033[0m'

    print()
    print(f'{bold}Serving:{reset} {content_path.name}')
    print(f'  → {cyan}http://localhost:{actual_port}{reset}')
    print(f'  {dim}Content: {content_path.resolve()}{reset}')
    print(f'  {dim}Theme:   {theme_dir}{reset}')
    print(f'  {dim}Corpus:  {corpus_root.resolve()}{reset}')
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped')
        server.server_close()


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print('Usage: server.py <content_path> <shape_path> <corpus_root>')
        sys.exit(1)
    serve(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
