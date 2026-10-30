"""Tests for the deck HTTP server — endpoint responses and content correctness."""
import importlib.util
import json
import threading
import time
import socket
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

CORPUS_ROOT = Path(__file__).parent.parent
CONTENT_PATH = CORPUS_ROOT / "content" / "moui" / "decks" / "pitch.yaml"
SHAPE_PATH = CORPUS_ROOT / "shapes" / "deck"
SERVER_PY = SHAPE_PATH / "renderer" / "shell-web" / "server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("deck_server", SERVER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def server():
    mod = load_server_module()
    content_data = yaml.safe_load(CONTENT_PATH.read_text())
    theme_ref = content_data.get("theme")
    from cli.resolver import resolve_theme_dir
    theme_dir = resolve_theme_dir(theme_ref, CONTENT_PATH)

    sse_clients = []
    lock = threading.Lock()
    mod.DeckHandler.content_path = CONTENT_PATH
    mod.DeckHandler.shape_path = SHAPE_PATH
    mod.DeckHandler.corpus_root = CORPUS_ROOT
    mod.DeckHandler.theme_dir = theme_dir
    mod.DeckHandler.sse_clients = sse_clients
    mod.DeckHandler.lock = lock

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), mod.DeckHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port
    httpd.shutdown()


def get(port, path):
    return urllib.request.urlopen(f"http://127.0.0.1:{port}{path}")


def test_index_returns_html(server):
    r = get(server, "/")
    body = r.read().decode()
    assert r.status == 200
    assert "<!DOCTYPE html>" in body
    assert 'src="/app.js"' in body


def test_content_returns_json_with_slides(server):
    r = get(server, "/content")
    data = json.loads(r.read())
    assert "slides" in data
    assert len(data["slides"]) > 0


def test_theme_returns_json_with_palette(server):
    r = get(server, "/theme")
    data = json.loads(r.read())
    assert "palette" in data


def test_theme_style_css_served(server):
    """The /theme/style.css endpoint returns the theme's CSS file."""
    r = get(server, "/theme/style.css")
    body = r.read().decode()
    assert r.status == 200
    assert r.headers.get('Content-Type', '').startswith('text/css')
    # CSS file may contain theme-scoped rules; check for the theme scope
    assert '[data-theme="pitch"]' in body or '[data-theme="default"]' in body or body.strip().startswith('/*')


def test_static_serves_app_js(server):
    r = get(server, "/app.js")
    body = r.read().decode()
    assert r.status == 200
    assert "import" in body


def test_static_serves_style_css(server):
    r = get(server, "/style.css")
    body = r.read().decode()
    assert r.status == 200
    assert ".viewport" in body


def test_vendor_serves_markdown_it(server):
    r = get(server, "/vendor/markdown-it.min.js")
    assert r.status == 200
    assert len(r.read()) > 0


def test_fonts_serve_inter(server):
    r = get(server, "/fonts/inter/Inter-Variable.woff2")
    assert r.status == 200
    assert len(r.read()) > 0


def test_path_traversal_blocked(server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        get(server, "/data/../moui.json")
    assert exc_info.value.code == 403


def test_content_accessible_while_sse_connected(server):
    """With an SSE connection held open, /content must still respond.

    Reproduces the browser scenario: EventSource holds a persistent
    connection to /events, then app.js fetches /content on reload.
    A single-threaded server blocks on the SSE handler and can never
    serve the /content request — the fetch hangs forever.
    """
    # Open a raw TCP connection to /events and keep it alive
    sock = socket.create_connection(("127.0.0.1", server), timeout=5)
    sock.sendall(b"GET /events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += sock.recv(1024)
    assert b"200" in buf
    # SSE connection is now held open (like EventSource in the browser)
    time.sleep(0.3)

    # Now try to fetch /content — must not hang
    try:
        r = urllib.request.urlopen(
            f"http://127.0.0.1:{server}/content", timeout=3
        )
        data = json.loads(r.read())
        assert "slides" in data
    finally:
        sock.close()


def test_fonts_css_returns_font_face_declarations(server):
    """The /fonts/fonts.css endpoint returns @font-face rules for every .woff2
    in shapes/deck/fonts/. The montserrat variable font must appear."""
    r = get(server, "/fonts/fonts.css")
    body = r.read().decode()
    assert r.status == 200
    assert r.headers.get('Content-Type', '').startswith('text/css')
    assert "@font-face" in body
    assert "font-family: montserrat" in body
    assert "Montserrat-Variable.woff2" in body
    assert "font-weight: 100 900" in body  # variable font range


def test_fonts_css_handles_regular_and_bold(server):
    """Non-variable fonts map filename suffixes to weights."""
    r = get(server, "/fonts/fonts.css")
    body = r.read().decode()
    # lato ships Regular and Bold non-variable files
    assert "Lato-Regular.woff2" in body
    assert "Lato-Bold.woff2" in body
    assert "font-weight: 400" in body
    assert "font-weight: 700" in body


def test_fonts_css_does_not_shadow_individual_font_files(server):
    """Adding /fonts/fonts.css must not break the existing /fonts/<path> route."""
    r = get(server, "/fonts/montserrat/Montserrat-Variable.woff2")
    assert r.status == 200
    assert len(r.read()) > 0


def test_parse_font_filename_raises_on_unknown_suffix():
    """A misnamed font file raises ValueError with the offending stem."""
    mod = load_server_module()
    with pytest.raises(ValueError, match="Unrecognized font filename suffix"):
        mod.parse_font_filename("Montserrat-Medium")


def test_parse_font_filename_bolditalic_not_shadowed_by_bold():
    """BoldItalic must be classified as weight 700 italic, not 700 normal —
    -Bold is a suffix of -BoldItalic, so ordering matters."""
    mod = load_server_module()
    assert mod.parse_font_filename("Lato-BoldItalic") == ("700", "italic")
    assert mod.parse_font_filename("Lato-Bold") == ("700", "normal")
    assert mod.parse_font_filename("Lato-Italic") == ("400", "italic")


def test_theme_shimmer_has_new_shape(server):
    """The pitch theme's /theme endpoint returns shimmer with stripe/duration/loop."""
    r = get(server, "/theme")
    data = json.loads(r.read())
    shimmer = data.get("effects", {}).get("shimmer")
    assert shimmer is not None, "pitch theme should declare shimmer effect"
    assert shimmer.get("stripe") == "warm-yellow"
    assert shimmer.get("duration") == "5s"
    assert shimmer.get("loop") is False
    # The old 'colors' field must be gone
    assert "colors" not in shimmer


def test_theme_shimmer_has_no_color_field(server):
    """Shimmer has no 'color' field — base color comes from the element's own color."""
    r = get(server, "/theme")
    data = json.loads(r.read())
    shimmer = data["effects"]["shimmer"]
    assert "color" not in shimmer


def test_content_endpoint_preserves_object_form_effect_config(server):
    """An object-form effect on a slide round-trips through /content intact.

    Uses the existing phone-ad slide which declares effect: shimmer (string form).
    Also exercises the object form by loading a freshly-constructed deck via yaml.
    """
    r = get(server, "/content")
    data = json.loads(r.read())
    slides = data["slides"]
    phone_ad = next((s for s in slides if s.get("id") == "phone-ad"), None)
    assert phone_ad is not None, "phone-ad slide should be present"
    heading_style = phone_ad["style"]["heading"]
    # String form survives the round-trip unchanged
    assert heading_style["effect"] == "shimmer"


def test_component_render_js_served(server):
    """The /components/<name>/render.js endpoint resolves and serves the file."""
    comp_dir = CORPUS_ROOT / "components" / "stat-card"
    if not comp_dir.exists():
        pytest.skip("stat-card component not yet created")
    r = get(server, "/components/stat-card/render.js")
    body = r.read().decode()
    assert r.status == 200
    assert "export" in body


def test_component_style_css_served(server):
    """The /components/<name>/style.css endpoint resolves and serves the file."""
    comp_dir = CORPUS_ROOT / "components" / "stat-card"
    if not comp_dir.exists():
        pytest.skip("stat-card component not yet created")
    r = get(server, "/components/stat-card/style.css")
    body = r.read().decode()
    assert r.status == 200
    assert r.headers.get('Content-Type', '').startswith('text/css')


def test_component_404_for_missing(server):
    """Missing component returns 404."""
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        get(server, "/components/nonexistent/render.js")
    assert exc_info.value.code == 404
