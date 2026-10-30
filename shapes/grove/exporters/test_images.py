"""Tests for grove image processor."""
import json
import hashlib
from pathlib import Path
from PIL import Image
import pytest

from images import process_images, _compute_image_hash, _scan_post_image_refs


# --- Fixtures ---

@pytest.fixture
def assets_dir(tmp_path):
    """Create a temporary assets directory with test images."""
    assets = tmp_path / "assets"
    assets.mkdir()
    return assets


@pytest.fixture
def sample_png(assets_dir):
    """Create a 1600x900 test PNG."""
    img = Image.new("RGB", (1600, 900), color=(100, 150, 200))
    path = assets_dir / "photo.png"
    img.save(path, "PNG")
    return path


@pytest.fixture
def small_png(assets_dir):
    """Create a 400x300 PNG (smaller than all breakpoints except 480 would upscale)."""
    img = Image.new("RGB", (400, 300), color=(200, 100, 50))
    path = assets_dir / "tiny.png"
    img.save(path, "PNG")
    return path


@pytest.fixture
def sample_jpg(assets_dir):
    """Create a 1200x800 test JPG."""
    img = Image.new("RGB", (1200, 800), color=(50, 100, 150))
    path = assets_dir / "banner.jpg"
    img.save(path, "JPEG")
    return path


@pytest.fixture
def sample_svg(assets_dir):
    """Create a test SVG file."""
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40"/></svg>'
    path = assets_dir / "diagram.svg"
    path.write_text(svg)
    return path


@pytest.fixture
def sample_gif(assets_dir):
    """Create a test GIF (single frame for simplicity)."""
    img = Image.new("RGB", (200, 200), color=(255, 0, 0))
    path = assets_dir / "animation.gif"
    img.save(path, "GIF")
    return path


@pytest.fixture
def posts_with_images():
    """Sample posts list with image references in body."""
    return [
        {"slug": "cloud-act", "body": "Some text\n\n![caption](assets/photo.png)\n\nMore text."},
        {"slug": "welcome", "body": "Hello\n\n![diagram](assets/diagram.svg)\n\nWorld."},
        {"slug": "about", "body": "No images here."},
    ]


# --- Hash tests ---

class TestComputeImageHash:
    def test_returns_12_hex_chars(self, sample_png):
        h = _compute_image_hash(sample_png)
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self, sample_png):
        assert _compute_image_hash(sample_png) == _compute_image_hash(sample_png)

    def test_different_content_different_hash(self, sample_png, small_png):
        assert _compute_image_hash(sample_png) != _compute_image_hash(small_png)


# --- Post scanning tests ---

class TestScanPostImageRefs:
    def test_finds_markdown_image(self):
        refs = _scan_post_image_refs([
            {"slug": "test", "body": "![alt](assets/photo.png)"},
        ])
        assert "assets/photo.png" in refs
        assert "test" in refs["assets/photo.png"]

    def test_finds_html_img(self):
        refs = _scan_post_image_refs([
            {"slug": "test", "body": '<img src="assets/photo.png" alt="x">'},
        ])
        assert "assets/photo.png" in refs
        assert "test" in refs["assets/photo.png"]

    def test_multiple_posts_same_image(self):
        refs = _scan_post_image_refs([
            {"slug": "a", "body": "![x](assets/shared.png)"},
            {"slug": "b", "body": "![y](assets/shared.png)"},
        ])
        assert set(refs["assets/shared.png"]) == {"a", "b"}

    def test_ignores_external_urls(self):
        refs = _scan_post_image_refs([
            {"slug": "test", "body": "![x](https://example.com/photo.png)"},
        ])
        assert len(refs) == 0

    def test_no_images_returns_empty(self):
        refs = _scan_post_image_refs([
            {"slug": "test", "body": "Just text."},
        ])
        assert len(refs) == 0


# --- Full processing tests ---

class TestProcessImages:
    def test_generates_variants_for_png(self, assets_dir, sample_png, posts_with_images):
        dist = assets_dir.parent / "dist"
        dist.mkdir()
        import shutil
        shutil.copytree(assets_dir, dist / "assets")

        manifest = process_images(assets_dir, dist, posts_with_images)

        entry = manifest["assets/photo.png"]
        assert entry["source_hash"]
        assert entry["passthrough"] is False
        assert entry["encrypted"] is False
        assert entry["original"]["format"] == "png"
        assert entry["original"]["og_safe"] is True
        assert entry["original"]["width"] == 1600
        assert entry["original"]["height"] == 900

        # Should have variants for 480, 960, 1440 in webp + png = 6 variants
        assert len(entry["variants"]) == 6
        formats = {v["format"] for v in entry["variants"]}
        assert formats == {"webp", "png"}
        widths = {v["width"] for v in entry["variants"]}
        assert widths == {480, 960, 1440}

    def test_no_upscaling(self, assets_dir, small_png, posts_with_images):
        dist = assets_dir.parent / "dist"
        dist.mkdir()
        import shutil
        shutil.copytree(assets_dir, dist / "assets")

        posts = [{"slug": "test", "body": "![x](assets/tiny.png)"}]
        manifest = process_images(assets_dir, dist, posts)

        entry = manifest["assets/tiny.png"]
        # 400px wide — no 480, 960, or 1440 variants (all would upscale)
        assert len(entry["variants"]) == 0

    def test_svg_passthrough(self, assets_dir, sample_svg, posts_with_images):
        dist = assets_dir.parent / "dist"
        dist.mkdir()
        import shutil
        shutil.copytree(assets_dir, dist / "assets")

        manifest = process_images(assets_dir, dist, posts_with_images)

        entry = manifest["assets/diagram.svg"]
        assert entry["passthrough"] is True
        assert entry["original"]["format"] == "svg"
        assert entry["original"]["og_safe"] is False
        assert "variants" not in entry or len(entry.get("variants", [])) == 0

    def test_gif_passthrough(self, assets_dir, sample_gif):
        dist = assets_dir.parent / "dist"
        dist.mkdir()
        import shutil
        shutil.copytree(assets_dir, dist / "assets")

        posts = [{"slug": "test", "body": "![x](assets/animation.gif)"}]
        manifest = process_images(assets_dir, dist, posts)

        entry = manifest["assets/animation.gif"]
        assert entry["passthrough"] is True

    def test_post_slugs_populated(self, assets_dir, sample_png, sample_svg, posts_with_images):
        dist = assets_dir.parent / "dist"
        dist.mkdir()
        import shutil
        shutil.copytree(assets_dir, dist / "assets")

        manifest = process_images(assets_dir, dist, posts_with_images)

        assert "cloud-act" in manifest["assets/photo.png"]["post_slugs"]
        assert "welcome" in manifest["assets/diagram.svg"]["post_slugs"]

    def test_grove_level_asset_has_empty_post_slugs(self, assets_dir, sample_png):
        """An image not referenced by any post gets empty post_slugs."""
        dist = assets_dir.parent / "dist"
        dist.mkdir()
        import shutil
        shutil.copytree(assets_dir, dist / "assets")

        manifest = process_images(assets_dir, dist, posts=[])

        assert manifest["assets/photo.png"]["post_slugs"] == []

    def test_variant_files_written_to_dist(self, assets_dir, sample_png):
        dist = assets_dir.parent / "dist"
        dist.mkdir()
        import shutil
        shutil.copytree(assets_dir, dist / "assets")

        posts = [{"slug": "test", "body": "![x](assets/photo.png)"}]
        manifest = process_images(assets_dir, dist, posts)

        for variant in manifest["assets/photo.png"]["variants"]:
            variant_path = dist / variant["path"]
            assert variant_path.exists(), f"Missing variant: {variant['path']}"

    def test_manifest_written_to_dist(self, assets_dir, sample_png):
        dist = assets_dir.parent / "dist"
        dist.mkdir()
        import shutil
        shutil.copytree(assets_dir, dist / "assets")

        process_images(assets_dir, dist, posts=[])

        manifest_path = dist / "assets" / "image-manifest.json"
        assert manifest_path.exists()
        loaded = json.loads(manifest_path.read_text())
        assert "assets/photo.png" in loaded

    def test_jpg_variants_keep_jpg_format(self, assets_dir, sample_jpg):
        dist = assets_dir.parent / "dist"
        dist.mkdir()
        import shutil
        shutil.copytree(assets_dir, dist / "assets")

        posts = [{"slug": "test", "body": "![x](assets/banner.jpg)"}]
        manifest = process_images(assets_dir, dist, posts)

        entry = manifest["assets/banner.jpg"]
        orig_format_variants = [v for v in entry["variants"] if v["format"] == "jpg"]
        assert len(orig_format_variants) > 0


# --- Cache tests ---

class TestProcessImagesCache:
    def test_skips_unchanged_images(self, assets_dir, sample_png):
        dist = assets_dir.parent / "dist"
        dist.mkdir()
        import shutil
        shutil.copytree(assets_dir, dist / "assets")

        posts = [{"slug": "test", "body": "![x](assets/photo.png)"}]

        # First build
        manifest1 = process_images(assets_dir, dist, posts)
        # Capture variant mtimes
        mtimes = {}
        for v in manifest1["assets/photo.png"]["variants"]:
            mtimes[v["path"]] = (dist / v["path"]).stat().st_mtime

        # Second build — same source, should skip
        manifest2 = process_images(assets_dir, dist, posts, previous_manifest=manifest1)
        assert manifest2["assets/photo.png"]["source_hash"] == manifest1["assets/photo.png"]["source_hash"]
