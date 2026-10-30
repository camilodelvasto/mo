"""Deck PDF exporter — captures rendered slides via headless Chromium.

Uses Playwright to start the deck server, navigate to each slide,
and capture a multi-page PDF at the slide aspect ratio. The HTML
renderer does all the visual work — this module just captures it.

Dependencies (declared in shape.manifest.yaml under export.pdf):
    playwright>=1.40
    Pillow>=10.0
    System: chromium (installed via `playwright install chromium`)
"""
import importlib.util
import socket
import threading
import time
from pathlib import Path

import yaml


def _find_free_port() -> int:
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(content_path: Path, shape_path: Path, corpus_root: Path, port: int):
    """Start the deck server in a background thread. Returns the server instance."""
    from http.server import ThreadingHTTPServer

    server_py = shape_path / "renderer" / "shell-web" / "server.py"
    spec = importlib.util.spec_from_file_location("deck_server", server_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    content_data = yaml.safe_load(content_path.read_text())
    theme_name = content_data.get("theme")
    if not theme_name:
        raise ValueError(f"No theme field in {content_path}")

    mod.DeckHandler.content_path = content_path
    mod.DeckHandler.shape_path = shape_path
    mod.DeckHandler.corpus_root = corpus_root
    mod.DeckHandler.theme_name = theme_name
    mod.DeckHandler.sse_clients = []
    mod.DeckHandler.lock = threading.Lock()

    server = ThreadingHTTPServer(("127.0.0.1", port), mod.DeckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _wait_for_server(port: int, timeout: float = 5.0):
    """Wait until the server is accepting connections."""
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            return
        except Exception:
            time.sleep(0.1)
    raise TimeoutError(f"Server on port {port} did not start within {timeout}s")


_EXPORT_CSS = """
.hamburger, .slide-counter, .sidebar, .sidebar-backdrop { display: none; }
.slide.scrollable, .slide .scrollable { overflow: visible; max-height: none; }
"""


def export(content_path: Path, shape_path: Path, corpus_root: Path, output_path: Path) -> Path:
    """Export a deck to PDF via headless Chromium capture.

    Starts the deck server, navigates to each slide, captures them
    into a single PDF at 1280x720 (16:9 aspect ratio).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "PDF export requires Playwright.\n"
            "Install with: pip install playwright && playwright install chromium"
        )

    try:
        from PIL import Image
    except ImportError:
        raise SystemExit(
            "PDF assembly requires Pillow.\n"
            "Run: pip install Pillow"
        )

    content_data = yaml.safe_load(content_path.read_text())
    slides = content_data.get("slides", [])
    slide_count = len(slides)

    port = _find_free_port()
    server = _start_server(content_path, shape_path, corpus_root, port)

    try:
        _wait_for_server(port)
        base_url = f"http://127.0.0.1:{port}"

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})

            screenshots = []
            for i in range(slide_count):
                page.goto(f"{base_url}/#{i + 1}", wait_until="load")
                page.wait_for_selector(".slide", state="visible", timeout=10000)

                # Hide UI chrome, unlock scrollable overflow for full capture
                page.add_style_tag(content=_EXPORT_CSS)

                # Wait for images to decode and artifact JS to initialize
                page.evaluate("""() => {
                    const imgs = document.querySelectorAll('img');
                    return Promise.all(Array.from(imgs).map(img =>
                        img.complete ? Promise.resolve() : new Promise(r => { img.onload = r; img.onerror = r; })
                    ));
                }""")

                # Wait for reveal animations and artifact JS to settle
                page.wait_for_timeout(1500)

                # For scrollable slides, expand viewport to capture full content
                slide_el = page.query_selector(".slide")
                if slide_el:
                    scroll_height = slide_el.evaluate("el => el.scrollHeight")
                    if scroll_height > 720:
                        page.set_viewport_size({"width": 1280, "height": scroll_height})
                        page.wait_for_timeout(200)

                screenshots.append(page.screenshot(type="png"))

                # Reset viewport for next slide
                page.set_viewport_size({"width": 1280, "height": 720})

            browser.close()

        # Assemble into PDF via Pillow — each page keeps its natural size
        import io
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pil_images = [Image.open(io.BytesIO(img)).convert("RGB") for img in screenshots]

        if pil_images:
            pil_images[0].save(
                str(output_path),
                save_all=True,
                append_images=pil_images[1:],
                resolution=96,
            )

    finally:
        server.shutdown()

    return output_path
