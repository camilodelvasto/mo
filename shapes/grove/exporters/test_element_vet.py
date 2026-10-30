import pytest
from element_vet import vet_html, VetError


class TestVetHtml:
    def test_clean_markup_passes(self):
        vet_html('<section class="hero"><h1>Hi</h1><img src="assets/x.png" alt="x"></section>')

    def test_disallowed_tag_throws(self):
        with pytest.raises(VetError, match="iframe"):
            vet_html('<iframe src="x"></iframe>')

    def test_inline_handler_throws(self):
        with pytest.raises(VetError, match="on"):
            vet_html('<button onclick="x()">go</button>')

    def test_external_link_tag_throws(self):
        with pytest.raises(VetError, match="external"):
            vet_html('<link rel="stylesheet" href="https://fonts.googleapis.com/x">')

    def test_external_script_src_throws(self):
        with pytest.raises(VetError, match="external"):
            vet_html('<script src="https://cdn.tailwindcss.com"></script>')

    def test_remote_img_throws(self):
        with pytest.raises(VetError, match="external"):
            vet_html('<img src="https://evil.example/x.png">')

    def test_local_img_passes(self):
        vet_html('<img src="assets/x.png" alt="x">')

    def test_external_url_in_style_throws(self):
        with pytest.raises(VetError, match="external"):
            vet_html('<style>@import url(https://fonts.googleapis.com/x);</style>')

    def test_declared_origin_passes(self):
        vet_html('<img src="https://cdn.allowed.example/x.png">',
                 allowed_origins=["https://cdn.allowed.example"])


class TestProtocolBlocking:
    def test_javascript_href_throws(self):
        with pytest.raises(VetError, match="disallowed protocol"):
            vet_html('<a href="javascript:alert(1)">click</a>')

    def test_vbscript_href_throws(self):
        with pytest.raises(VetError, match="disallowed protocol"):
            vet_html('<a href="vbscript:msgbox(1)">click</a>')

    def test_data_text_html_throws(self):
        with pytest.raises(VetError, match="data:"):
            vet_html('<img src="data:text/html,<h1>evil</h1>">')

    def test_data_image_passes(self):
        vet_html('<img src="data:image/png;base64,AAAA" alt="x">')


class TestCSSUrlOrigin:
    def test_declared_origin_in_style_url_passes(self):
        vet_html(
            '<style>body { background: url(https://cdn.example.com/bg.png); }</style>',
            allowed_origins=["https://cdn.example.com"],
        )

    def test_undeclared_origin_in_style_url_throws(self):
        with pytest.raises(VetError, match="external"):
            vet_html('<style>body { background: url(https://evil.example/bg.png); }</style>')


class TestOriginBoundary:
    def test_subdomain_prefix_bypass_throws(self):
        with pytest.raises(VetError, match="external"):
            vet_html(
                '<img src="https://cdn.allowed.example.evil.com/x.png">',
                allowed_origins=["https://cdn.allowed.example"],
            )

    def test_exact_origin_with_path_passes(self):
        vet_html(
            '<img src="https://cdn.allowed.example/assets/x.png">',
            allowed_origins=["https://cdn.allowed.example"],
        )


class TestSVGAttrs:
    def test_svg_with_viewbox_and_path_passes(self):
        vet_html(
            '<svg viewBox="0 0 10 10">'
            '<path d="M0 0L10 10" fill="red"></path>'
            '</svg>'
        )
