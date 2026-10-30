"""Tests for image HTML post-processing."""
import pytest
from image_tags import transform_images


def _manifest_entry(src="assets/photo.png", width=1600, height=900, fmt="png"):
    """Build a manifest entry for testing."""
    variants = []
    for w in [480, 960, 1440]:
        if w < width:
            for f in ["webp", fmt]:
                stem = src.split("/")[-1].rsplit(".", 1)[0]
                variants.append({
                    "path": f"assets/{stem}-{w}w.{f}",
                    "width": w,
                    "format": f,
                    "encrypted": False,
                })
    return {
        src: {
            "source_hash": "abc123def456",
            "post_slugs": ["test"],
            "passthrough": False,
            "encrypted": False,
            "original": {
                "path": src,
                "width": width,
                "height": height,
                "format": fmt,
                "og_safe": True,
            },
            "variants": variants,
        }
    }


def _svg_manifest():
    return {
        "assets/diagram.svg": {
            "source_hash": "aaa111bbb222",
            "post_slugs": ["test"],
            "passthrough": True,
            "encrypted": False,
            "original": {"path": "assets/diagram.svg", "format": "svg", "og_safe": False},
        }
    }


class TestStandaloneImage:
    def test_standalone_img_becomes_figure_picture(self):
        html = '<p><img src="assets/photo.png" alt="A photo"></p>'
        result = transform_images(html, _manifest_entry())
        assert "<figure>" in result
        assert "<picture>" in result
        assert "<figcaption>A photo</figcaption>" in result
        assert "<p>" not in result  # <p> replaced by <figure>

    def test_first_image_is_eager(self):
        html = '<p><img src="assets/photo.png" alt="A photo"></p>'
        result = transform_images(html, _manifest_entry())
        assert 'loading="eager"' in result

    def test_second_image_is_lazy(self):
        html = ('<p><img src="assets/photo.png" alt="First"></p>'
                '<p><img src="assets/photo.png" alt="Second"></p>')
        result = transform_images(html, _manifest_entry())
        parts = result.split("<figure>")
        # First figure should have eager
        assert 'loading="eager"' in parts[1]
        # Second figure should have lazy
        assert 'loading="lazy"' in parts[2]

    def test_empty_alt_no_figcaption(self):
        html = '<p><img src="assets/photo.png" alt=""></p>'
        result = transform_images(html, _manifest_entry())
        assert "<figcaption>" not in result

    def test_srcset_has_all_widths(self):
        html = '<p><img src="assets/photo.png" alt="x"></p>'
        result = transform_images(html, _manifest_entry())
        assert "480w" in result
        assert "960w" in result
        assert "1440w" in result

    def test_webp_source_first(self):
        html = '<p><img src="assets/photo.png" alt="x"></p>'
        result = transform_images(html, _manifest_entry())
        webp_pos = result.index('type="image/webp"')
        png_pos = result.index('type="image/png"')
        assert webp_pos < png_pos

    def test_fallback_img_uses_original(self):
        html = '<p><img src="assets/photo.png" alt="x"></p>'
        result = transform_images(html, _manifest_entry())
        assert 'src="/assets/photo.png"' in result

    def test_sizes_attribute(self):
        html = '<p><img src="assets/photo.png" alt="x"></p>'
        result = transform_images(html, _manifest_entry())
        assert 'sizes="(max-width: 600px) 100vw, 600px"' in result


class TestInlineImage:
    def test_inline_img_no_figure(self):
        html = '<p>Text <img src="assets/photo.png" alt="inline"> more text.</p>'
        result = transform_images(html, _manifest_entry())
        assert "<figure>" not in result
        assert "<picture>" in result
        assert "<figcaption>" not in result
        assert "<p>" in result  # <p> preserved


class TestConventionParsing:
    def test_right_alignment(self):
        html = '<p><img src="assets/photo.png" alt="Caption|right"></p>'
        result = transform_images(html, _manifest_entry())
        assert 'class="align-right"' in result
        assert "<figcaption>Caption</figcaption>" in result

    def test_width_percentage(self):
        html = '<p><img src="assets/photo.png" alt="Caption|80%"></p>'
        result = transform_images(html, _manifest_entry())
        assert 'style="max-width:80%"' in result
        assert "<figcaption>Caption</figcaption>" in result

    def test_both_alignment_and_width(self):
        html = '<p><img src="assets/photo.png" alt="Caption|right|60%"></p>'
        result = transform_images(html, _manifest_entry())
        assert 'class="align-right"' in result
        assert 'style="max-width:60%"' in result
        assert "<figcaption>Caption</figcaption>" in result

    def test_no_convention_no_class(self):
        html = '<p><img src="assets/photo.png" alt="Plain caption"></p>'
        result = transform_images(html, _manifest_entry())
        assert 'class="align-' not in result
        assert 'style="max-width:' not in result


class TestPassthrough:
    def test_svg_no_picture(self):
        html = '<p><img src="assets/diagram.svg" alt="Diagram"></p>'
        result = transform_images(html, _svg_manifest())
        assert "<figure>" in result
        assert "<picture>" not in result
        assert 'src="/assets/diagram.svg"' in result
        assert "<figcaption>Diagram</figcaption>" in result

    def test_not_in_manifest_passthrough(self):
        html = '<p><img src="assets/unknown.png" alt="x"></p>'
        result = transform_images(html, {})
        assert result == html  # unchanged


class TestExternalUrls:
    def test_external_http_passthrough(self):
        html = '<p><img src="https://example.com/photo.png" alt="x"></p>'
        result = transform_images(html, _manifest_entry())
        assert result == html

    def test_external_protocol_relative_passthrough(self):
        html = '<p><img src="//cdn.example.com/photo.png" alt="x"></p>'
        result = transform_images(html, _manifest_entry())
        assert result == html


class TestNoVariants:
    def test_small_image_no_srcset(self):
        """Image too small for any variants gets figure but no picture."""
        manifest = {
            "assets/tiny.png": {
                "source_hash": "xxx",
                "post_slugs": ["test"],
                "passthrough": False,
                "encrypted": False,
                "original": {"path": "assets/tiny.png", "width": 400, "height": 300,
                             "format": "png", "og_safe": True},
                "variants": [],
            }
        }
        html = '<p><img src="assets/tiny.png" alt="Small"></p>'
        result = transform_images(html, manifest)
        assert "<figure>" in result
        assert "<picture>" not in result
        assert 'src="/assets/tiny.png"' in result


class TestBasePath:
    def test_subpath_prefix_in_srcset(self):
        html = '<p><img src="assets/photo.png" alt="x"></p>'
        result = transform_images(html, _manifest_entry(), base_path="/grove")
        assert "/grove/assets/photo-480w.webp 480w" in result
        assert "/grove/assets/photo-960w.png 960w" in result

    def test_subpath_prefix_in_fallback_src(self):
        html = '<p><img src="assets/photo.png" alt="x"></p>'
        result = transform_images(html, _manifest_entry(), base_path="/grove")
        assert 'src="/grove/assets/photo.png"' in result

    def test_subpath_prefix_in_passthrough(self):
        html = '<p><img src="assets/diagram.svg" alt="Diagram"></p>'
        result = transform_images(html, _svg_manifest(), base_path="/grove")
        assert 'src="/grove/assets/diagram.svg"' in result

    def test_empty_base_path_uses_root_relative(self):
        html = '<p><img src="assets/photo.png" alt="x"></p>'
        result = transform_images(html, _manifest_entry(), base_path="")
        assert 'src="/assets/photo.png"' in result
