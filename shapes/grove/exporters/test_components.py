"""Tests for grove build-time components."""
from pathlib import Path

import pytest

from components import render_header, render_footer, render_card, render_app_rail, _render_action


def test_capability_key_is_rejected_with_rename_message():
    with pytest.raises(ValueError, match="feature:"):
        _render_action({"label": "Archive", "capability": "archive"}, "", None)


def test_href_action_is_base_path_prefixed():
    # a root-relative href (e.g. the chat route /chatbot) must carry the grove's
    # base_path, exactly like the archive feature — else a sub-path grove links to
    # the wrong place (the page publishes to {base_path}/chatbot, not /chatbot).
    html = _render_action({"label": "Chatbot", "href": "/chatbot", "style": "accent"}, "/hub", None)
    assert 'href="/hub/chatbot"' in html


def test_href_action_empty_base_path_unchanged():
    html = _render_action({"label": "ES", "href": "/es", "style": "ghost"}, "", None)
    assert 'href="/es"' in html


def test_href_action_root_base_path_no_double_slash():
    html = _render_action({"label": "X", "href": "/chatbot"}, "/", None)
    assert 'href="/chatbot"' in html and "//chatbot" not in html


def test_absolute_url_href_is_not_prefixed():
    html = _render_action({"label": "Ext", "href": "https://example.com/x"}, "/hub", None)
    assert 'href="https://example.com/x"' in html


def _grove():
    return {
        "id": "test-grove", "title": "Test Grove", "lang": "en",
        "og": {"title": "Test", "description": "A test.", "image": "og.png"},
        "defaults": {"layout": "article"},
        "rss": {"enabled": True},
        "header": {
            "actions": [
                {"label": "Archive", "feature": "archive", "style": "ghost"},
                {"label": "Search", "feature": "search", "style": "accent", "icon": "search"},
            ]
        },
    }


def _ctx(base_url="https://example.com", base_path="", on_clear="reload"):
    icons_dir = Path(__file__).resolve().parent.parent / "icons"
    return {
        "base_url": base_url, "base_path": base_path,
        "theme_css": "", "on_clear": on_clear,
        "icons_dir": icons_dir,
        "strings": {
            "toggle_theme": "Toggle theme",
            "clear_site": "Clear site data",
            "skip_to_content": "Skip to content",
        },
    }


def _post(**kw):
    base = {"title": "Welcome", "excerpt": "Hello world.", "url_path": "/welcome/",
            "publish_date": "2026-04-14", "publish_date_display": "2026-04-14",
            "tags": ["test"], "content_path": "welcome"}
    base.update(kw)
    return base


class TestRenderHeader:
    def test_contains_grove_title(self):
        html = render_header(_grove(), _ctx())
        assert "Test Grove" in html

    def test_archive_feature_renders_link(self):
        html = render_header(_grove(), _ctx())
        assert 'href="/archive/"' in html
        assert "Archive" in html

    def test_search_feature_renders_button(self):
        html = render_header(_grove(), _ctx())
        assert 'data-action="open-search"' in html
        assert "<button" in html

    def test_search_icon_renders_svg(self):
        html = render_header(_grove(), _ctx())
        assert "<svg" in html

    def test_custom_href_link(self):
        grove = _grove()
        grove["header"]["actions"].append(
            {"label": "ES", "href": "/es", "style": "ghost"}
        )
        html = render_header(grove, _ctx())
        assert 'href="/es"' in html
        assert "ES" in html

    def test_action_order_matches_declaration(self):
        html = render_header(_grove(), _ctx())
        archive_pos = html.index("Archive")
        search_pos = html.index("open-search")
        assert archive_pos < search_pos

    def test_accessible_landmarks(self):
        html = render_header(_grove(), _ctx())
        assert 'role="banner"' in html or "<header" in html

    def test_missing_header_renders_nothing(self):
        # No `header` block = no header declared = chromeless, not a crash.
        grove = _grove()
        del grove["header"]
        assert render_header(grove, _ctx()) == ""

    def test_declared_but_malformed_header_throws(self):
        # A header that IS declared must be well-formed — no fallback.
        grove = _grove()
        grove["header"] = {}            # declared but missing actions
        with pytest.raises(KeyError):
            render_header(grove, _ctx())

    def test_base_path_applied_to_archive(self):
        html = render_header(_grove(), _ctx(base_path="/blog"))
        assert 'href="/blog/archive/"' in html


class TestRenderFooter:
    def test_contains_rss_link(self):
        html = render_footer(_grove(), _ctx())
        assert "feed.xml" in html

    def test_contains_grove_title(self):
        html = render_footer(_grove(), _ctx())
        assert "Test Grove" in html

    def test_has_footer_element(self):
        html = render_footer(_grove(), _ctx())
        assert "<footer" in html

    def test_rss_hidden_when_disabled(self):
        grove = _grove()
        grove["rss"] = {"enabled": False}
        html = render_footer(grove, _ctx())
        assert "feed.xml" not in html

    def test_has_clear_site_button(self):
        html = render_footer(_grove(), _ctx())
        assert 'data-action="clear-site"' in html
        assert 'data-on-clear="reload"' in html

    def test_clear_site_url_redirect(self):
        html = render_footer(_grove(), _ctx(on_clear="https://example.com"))
        assert 'data-on-clear="https://example.com"' in html

    def test_clear_site_escapes_url(self):
        html = render_footer(_grove(), _ctx(on_clear="https://example.com/?a=1&b=2"))
        assert 'data-on-clear="https://example.com/?a=1&amp;b=2"' in html

    def test_footer_uses_strings_for_toggle_theme(self):
        ctx = _ctx()
        ctx["strings"]["toggle_theme"] = "Cambiar tema"
        html = render_footer(_grove(), ctx)
        assert 'aria-label="Cambiar tema"' in html

    def test_footer_uses_strings_for_clear_site(self):
        ctx = _ctx()
        ctx["strings"]["clear_site"] = "Borrar datos"
        html = render_footer(_grove(), ctx)
        assert 'aria-label="Borrar datos"' in html


class TestRenderCard:
    def test_has_title_link(self):
        html = render_card(_post())
        assert "Welcome" in html
        assert 'href="/welcome/"' in html

    def test_has_date(self):
        html = render_card(_post())
        assert "2026-04-14" in html
        assert "<time" in html

    def test_has_excerpt(self):
        html = render_card(_post())
        assert "Hello world." in html

    def test_has_card_body_wrapper(self):
        html = render_card(_post())
        assert 'class="card-body"' in html

    def test_thumbnail_rendered_when_present(self):
        html = render_card(_post(_thumbnail="assets/og.png"))
        assert 'class="card-thumbnail"' in html
        assert 'src="/assets/og.png"' in html

    def test_no_thumbnail_when_absent(self):
        html = render_card(_post())
        assert "card-thumbnail" not in html

    def test_tags_rendered_when_present(self):
        html = render_card(_post(tags=["moui", "local-first"]))
        assert 'class="card-tags"' in html
        assert 'class="card-tag"' in html
        assert "moui" in html
        assert "local-first" in html

    def test_no_tags_when_absent(self):
        html = render_card(_post(tags=[]))
        assert "card-tags" not in html

    def test_no_tags_when_none(self):
        post = _post()
        post.pop("tags", None)
        html = render_card(post)
        assert "card-tags" not in html

    def test_card_bg_override(self):
        html = render_card(_post(card={"bg": "#1a1a22"}))
        assert "--color-card-bg-resolved: #1a1a22" in html

    def test_card_color_override(self):
        html = render_card(_post(card={"color": "#ffffff"}))
        assert "--color-text-resolved: #ffffff" in html
        assert "--color-text-secondary-resolved: #ffffff" in html

    def test_no_overrides_without_card(self):
        html = render_card(_post())
        assert "--color-card-bg-resolved" not in html
        assert "--color-text-resolved" not in html


def _rail_grove():
    return {"id": "g", "title": "Test Grove",
            "header": {"actions": [
                {"label": "Chatbot", "href": "/chatbot", "style": "accent"},
                {"label": "Explorar", "href": "/explorar", "style": "accent"},
                {"label": "Buscar", "feature": "search", "style": "ghost"},
            ]},
            "rss": {"enabled": False}}


class TestRenderAppRail:
    def test_brand_title_renders(self):
        html = render_app_rail(_rail_grove(), _ctx())
        assert "Test Grove" in html

    def test_conversation_slot_present(self):
        html = render_app_rail(_rail_grove(), _ctx())
        assert "data-chat-sidebar-slot" in html

    def test_no_site_nav_in_rail(self):
        # Navigation belongs in the site header or nowhere — never duplicated into the
        # chat sidebar. The rail carries no header actions and no footer controls; the
        # brand link is the only way back to the site.
        html = render_app_rail(_rail_grove(), _ctx())
        assert "Explorar" not in html
        assert 'data-action="open-search"' not in html
        assert 'data-action="toggle-theme"' not in html
        assert 'data-action="clear-site"' not in html
