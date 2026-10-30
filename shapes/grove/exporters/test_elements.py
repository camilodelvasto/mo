import pytest
from pathlib import Path
from elements import resolve_element, emit_authored, ResolveError


def _grove():
    return {"id": "g", "title": "Test Grove", "lang": "en",
            "features": [{"id": "assistant", "type": "chat", "ask": "faq"}],
            "og": {"title": "T", "description": "d", "image": "og.png"}}


def _ctx():
    return {"base_url": "https://e.com", "base_path": "", "strings": {}}


def _el(tmp, rel, html, css=None, js=None):
    d = Path(tmp) / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(html, encoding="utf-8")
    if css: (d / "styles.css").write_text(css, encoding="utf-8")
    if js: (d / "script.js").write_text(js, encoding="utf-8")
    return d


def _resolve(item, tmp, page_folder=None, posts=(), page_route="/x"):
    return resolve_element(item, _grove(), _ctx(), grove_root=tmp,
                           page_folder=page_folder, page_route=page_route, posts=list(posts))


class TestResolve:
    def test_shared_element_prefixed(self, tmp_path):
        _el(tmp_path, "elements/hero", '<section class="hero"><h1>Hi</h1></section>', css=".hero{}")
        frag, script = _resolve("elements/hero", tmp_path)
        assert "Hi" in frag and "data-p-" in frag and "<style" in frag
        assert script is None

    def test_self_renders_page_folder_index(self, tmp_path):
        pf = _el(tmp_path, "pages/manifiesto", "<section>SELF</section>")
        frag, _ = _resolve("self", tmp_path, page_folder=pf)
        assert "SELF" in frag and "data-p-" in frag

    def test_self_without_index_throws(self, tmp_path):
        pf = Path(tmp_path) / "pages/empty"; pf.mkdir(parents=True)
        with pytest.raises(ResolveError, match="index.html"):
            _resolve("self", tmp_path, page_folder=pf)

    def test_bare_name_is_builtin(self, tmp_path):
        posts = [{"title": "P1", "url_path": "/p1/", "excerpt": "x",
                  "publish_date": "2026-01-01", "content_path": "p1", "card": {}}]
        frag, _ = _resolve("grid", tmp_path, posts=posts)
        assert "feed-grid" in frag and "P1" in frag

    def test_builtin_with_config(self, tmp_path):
        frag, _ = _resolve({"grid": {"limit": 0}}, tmp_path, posts=[])
        assert "feed-grid" in frag

    def test_feature_marker(self, tmp_path):
        frag, _ = _resolve({"feature": "assistant"}, tmp_path)
        assert "data-chat-root" in frag and 'data-ask="faq"' in frag

    def test_unknown_string_throws(self, tmp_path):
        with pytest.raises(ResolveError, match="unknown element"):
            _resolve("nope", tmp_path)

    def test_authored_script_inlined(self, tmp_path):
        _el(tmp_path, "elements/c", '<div class="c"></div>', js='document.querySelector(".c");')
        frag, script = _resolve("elements/c", tmp_path)
        assert '<script type="module">' in frag and script == 'document.querySelector(".c");'
