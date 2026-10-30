from pathlib import Path
from compose import compose_fragment, compose_page
from elements import _prefix_authored_urls


def _grove():
    return {"id": "g", "title": "Test Grove", "lang": "en",
            "features": [{"id": "assistant", "type": "chat", "ask": "faq"}],
            "og": {"title": "T", "description": "d", "image": "og.png"},
            "defaults": {"layout": "article"},
            "header": {"actions": []},
            "rss": {"enabled": False}}


def _ctx():
    icons_dir = Path(__file__).resolve().parent.parent / "icons"
    return {"base_url": "https://e.com", "base_path": "", "theme_css": ":root{}",
            "icons_dir": icons_dir, "on_clear": "reload",
            "strings": {"toggle_theme": "Toggle theme", "clear_site": "Clear site data",
                        "skip_to_content": "Skip to content"}}


def _page(tmp, route="/x", **kw):
    folder = Path(tmp) / "pages" / route.strip("/")
    folder.mkdir(parents=True, exist_ok=True)
    rec = {"route": route, "folder": folder, "title": "X", "layout": None,
           "og": None, "egress": None, "body": ["self"], "published": True,
           "discoverable": True, "excerpt": None}
    rec.update(kw)
    return rec


def test_fragment_self(tmp_path):
    p = _page(tmp_path, body=["self"])
    (p["folder"] / "index.html").write_text("<section>HELLO</section>")
    html, hashes = compose_fragment(p, _grove(), _ctx(), grove_root=tmp_path, posts=[], feature_endpoints={})
    assert "HELLO" in html and hashes == []


def test_fragment_grid_and_feature(tmp_path):
    posts = [{"title": "P1", "url_path": "/p1/", "excerpt": "x",
              "publish_date": "2026-01-01", "content_path": "p1", "card": {}}]
    p = _page(tmp_path, route="/chatbot", body=[{"grid": {"limit": 5}}, {"feature": "assistant"}])
    html, _ = compose_fragment(p, _grove(), _ctx(), grove_root=tmp_path, posts=posts,
                               feature_endpoints={"assistant": "https://ask.example.com"})
    assert "P1" in html and "data-chat-root" in html


def test_default_page_has_shell_chrome(tmp_path):
    p = _page(tmp_path, body=[{"grid": {}}])
    html = compose_page(p, _grove(), _ctx(), grove_root=tmp_path, posts=[], feature_endpoints={})
    assert "<!DOCTYPE html>" in html and "<header" in html and "connect-src 'none'" in html


def test_landing_layout_suppresses_chrome(tmp_path):
    p = _page(tmp_path, layout="landing", body=[{"grid": {}}])
    html = compose_page(p, _grove(), _ctx(), grove_root=tmp_path, posts=[], feature_endpoints={})
    assert "<header" not in html


def test_app_layout_suppresses_chrome(tmp_path):
    p = _page(tmp_path, route="/chatbot", layout="app",
              body=[{"feature": "assistant"}])
    html = compose_page(p, _grove(), _ctx(), grove_root=tmp_path, posts=[],
                        feature_endpoints={"assistant": "https://ask.example.com"})
    assert "site-header" not in html      # no site header on the app surface
    assert "site-footer" not in html      # no site footer either
    assert 'data-layout="app"' in html


def test_feature_grants_csp_and_marker(tmp_path):
    p = _page(tmp_path, route="/chatbot", body=[{"feature": "assistant"}])
    html = compose_page(p, _grove(), _ctx(), grove_root=tmp_path, posts=[],
                        feature_endpoints={"assistant": "https://ask.example.com"})
    assert "data-chat-root" in html and "connect-src https://ask.example.com" in html


def test_app_layout_wraps_body_in_rail_and_column(tmp_path):
    p = _page(tmp_path, route="/chatbot", layout="app",
              body=[{"feature": "assistant"}])
    html = compose_page(p, _grove(), _ctx(), grove_root=tmp_path, posts=[],
                        feature_endpoints={"assistant": "https://ask.example.com"})
    assert 'class="app-shell"' in html
    assert "data-chat-sidebar-slot" in html        # rail present
    assert 'class="app-column"' in html            # body composes into the column
    assert "data-chat-root" in html                # the feature still composed inside
    # rail comes before the column, and the feature is nested inside the column
    assert html.index("app-shell") < html.index("data-chat-root")
    assert html.index("app-column") < html.index("data-chat-root")


def test_app_layout_fragment_includes_rail(tmp_path):
    # The dev server fills #main from compose_fragment, so the app frame (rail +
    # column) must be in the fragment too — not only in the full compose_page.
    p = _page(tmp_path, route="/chatbot", layout="app",
              body=[{"feature": "assistant"}])
    html, _ = compose_fragment(p, _grove(), _ctx(), grove_root=tmp_path, posts=[],
                               feature_endpoints={"assistant": "https://ask.example.com"})
    assert 'class="app-shell"' in html
    assert "data-chat-sidebar-slot" in html
    assert 'class="app-column"' in html
    assert "data-chat-root" in html


def test_authored_root_relative_links_get_base_path(tmp_path):
    # cards link root-relative; the grove lives under /hub → prefix it.
    p = _page(tmp_path, body=["self"])
    (p["folder"] / "index.html").write_text(
        '<section><a href="/advisor">x</a><img src="/assets/c.png" alt="c"></section>')
    ctx = _ctx(); ctx["base_path"] = "/hub"
    html, _ = compose_fragment(p, _grove(), ctx, grove_root=tmp_path, posts=[], feature_endpoints={})
    assert 'href="/hub/advisor"' in html
    assert 'src="/hub/assets/c.png"' in html


def test_authored_absolute_and_protocol_relative_untouched():
    # _prefix_authored_urls must not touch absolute (scheme://) or protocol-relative (//)
    # URLs — only root-relative (/path) ones carry the base_path.
    html = '<section><a href="https://x.example/y">y</a><img src="//cdn/z.png" alt="z"></section>'
    result = _prefix_authored_urls(html, "/hub")
    assert 'href="https://x.example/y"' in result and 'src="//cdn/z.png"' in result


def test_authored_links_untouched_at_root(tmp_path):
    p = _page(tmp_path, body=["self"])
    (p["folder"] / "index.html").write_text('<section><a href="/advisor">x</a></section>')
    ctx = _ctx(); ctx["base_path"] = ""          # grove at site root → no prefix
    html, _ = compose_fragment(p, _grove(), ctx, grove_root=tmp_path, posts=[], feature_endpoints={})
    assert 'href="/advisor"' in html
