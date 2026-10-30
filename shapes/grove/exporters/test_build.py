"""Tests for grove build orchestrator."""
import hashlib
import json, pytest
from pathlib import Path
from build import build, BuildError, _compute_build_hash, _version_sw, _derive_base_path

BASE_URL = "http://localhost:4200"

def _setup_grove(tmp_path):
    grove_yaml = tmp_path / "grove.yaml"
    grove_yaml.write_text("""
id: test-grove
title: "Test Grove"
description: "A test grove."

lang: en
defaults:
  view: grid
  layout: article
  posts_per_page: 12
og:
  title: "Test"
  description: "Test grove."
  image: og.png
header:
  actions:
    - label: Archive
      feature: archive
      style: ghost
    - label: Search
      feature: search
      style: accent
      icon: search
rss:
  enabled: true
  max_items: 20
""")
    posts_dir = tmp_path / "posts"
    posts_dir.mkdir(parents=True)

    (posts_dir / "welcome.md").write_text("""---
title: "Welcome"
slug: welcome
published: true
publish_date: 2026-04-14
excerpt: "Hello world."
tags: [test]
---

# Welcome

Hello world.
""")

    (posts_dir / "draft.md").write_text("""---
title: "Draft"
published: false
publish_date: 2026-04-14
---

Draft content.
""")

    # Bare grove: no pages/ — the home is the default feed.
    return tmp_path

class TestBuild:
    def test_creates_dist(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert dist.exists()
        assert (dist / "index.html").exists()

    def test_post_html_exists(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert (dist / "welcome" / "index.html").exists()

    def test_draft_excluded(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert not (dist / "draft" / "index.html").exists()

    def test_feed_xml_exists(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert (dist / "feed.xml").exists()

    def test_feed_json_exists(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert (dist / "feed.json").exists()

    def test_sitemap_exists(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert (dist / "sitemap.xml").exists()

    def test_search_index_exists(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert (dist / "search-index.json").exists()

    def test_first_load_index_exists(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert (dist / "first-load-index.json").exists()

    def test_post_html_has_content(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        html = (dist / "welcome" / "index.html").read_text()
        assert "Welcome" in html
        assert "Hello world" in html

    def test_index_has_post_card(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        html = (dist / "index.html").read_text()
        assert "Welcome" in html

    def test_missing_og_throws(self, tmp_path):
        root = _setup_grove(tmp_path)
        (root / "grove.yaml").write_text("""
id: test-grove
title: "Test"
description: "Test."

lang: en
""")
        with pytest.raises(BuildError, match="og"):
            build(root, base_url=BASE_URL, crawlable="thin")

    def test_duplicate_slugs_throw(self, tmp_path):
        root = _setup_grove(tmp_path)
        posts_dir = root / "posts"
        (posts_dir / "duplicate.md").write_text("""---
title: "Duplicate"
slug: welcome
published: true
publish_date: 2026-04-14
---

Duplicate.
""")
        with pytest.raises(BuildError, match="Duplicate"):
            build(root, base_url=BASE_URL, crawlable="thin")

    def test_missing_grove_yaml_throws(self, tmp_path):
        (tmp_path / "posts").mkdir(parents=True)
        with pytest.raises(BuildError, match="grove.yaml"):
            build(tmp_path, base_url=BASE_URL, crawlable="thin")

    def test_missing_posts_dir_throws(self, tmp_path):
        (tmp_path / "grove.yaml").write_text("""
id: test
title: "T"
description: "D"

lang: en
og:
  title: "T"
  description: "D"
  image: img.png
""")
        with pytest.raises(BuildError, match="posts/"):
            build(tmp_path, base_url=BASE_URL, crawlable="thin")

class TestBuildSections:
    def test_section_index_generated(self, tmp_path):
        root = _setup_grove(tmp_path)
        arch_dir = root / "posts" / "architecture"
        arch_dir.mkdir()
        (arch_dir / "corpus-format.md").write_text("""---
title: "Corpus Format"
published: true
publish_date: 2026-04-14
excerpt: "How the corpus is structured."
tags: [architecture]
---

# Corpus Format

Details.
""")
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        section_index = dist / "architecture" / "index.html"
        assert section_index.exists()
        html = section_index.read_text()
        assert "Corpus Format" in html

    def test_section_index_skipped_when_explicit_index_exists(self, tmp_path):
        root = _setup_grove(tmp_path)
        arch_dir = root / "posts" / "architecture"
        arch_dir.mkdir()
        (arch_dir / "index.md").write_text("""---
title: "Architecture"
published: true
publish_date: 2026-04-14
excerpt: "Custom section index."
tags: [architecture]
---

# Architecture

Custom index content.
""")
        (arch_dir / "corpus-format.md").write_text("""---
title: "Corpus Format"
published: true
publish_date: 2026-04-14
excerpt: "How the corpus is structured."
tags: [architecture]
---

# Corpus Format

Details.
""")
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        section_index = dist / "architecture" / "index.html"
        assert section_index.exists()
        html = section_index.read_text()
        # Should contain the explicit index content, not auto-generated listing
        assert "Custom index content" in html


class TestBuildCollections:
    def test_collection_page_generated(self, tmp_path):
        root = _setup_grove(tmp_path)
        colls_dir = root / "content" / "collections"
        colls_dir.mkdir(parents=True)
        (colls_dir / "getting-started.yaml").write_text("""
id: getting-started
title: "Getting Started"
posts:
  - welcome
""")
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        coll_page = dist / "c" / "getting-started" / "index.html"
        assert coll_page.exists()
        html = coll_page.read_text()
        assert "Getting Started" in html
        assert "Welcome" in html

    def test_collection_missing_post_throws(self, tmp_path):
        root = _setup_grove(tmp_path)
        colls_dir = root / "content" / "collections"
        colls_dir.mkdir(parents=True)
        (colls_dir / "bad.yaml").write_text("""
id: bad
title: "Bad"
posts:
  - nonexistent
""")
        with pytest.raises(BuildError, match="nonexistent"):
            build(root, base_url=BASE_URL, crawlable="thin")

    def test_no_collections_dir_still_builds(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert dist.exists()
        assert not (dist / "c").exists()


class TestBuildArchive:
    def test_archive_page_exists(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert (dist / "archive" / "index.html").exists()

    def test_archive_contains_posts(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        html = (dist / "archive" / "index.html").read_text()
        assert "Welcome" in html


class TestBuildHash:
    def test_deterministic_same_inputs(self, tmp_path):
        (tmp_path / "a.css").write_bytes(b"body{color:red}")
        (tmp_path / "b.js").write_bytes(b"console.log(1)")
        h1 = _compute_build_hash(tmp_path)
        h2 = _compute_build_hash(tmp_path)
        assert h1 == h2

    def test_changes_when_content_changes(self, tmp_path):
        (tmp_path / "a.css").write_bytes(b"body{color:red}")
        h1 = _compute_build_hash(tmp_path)
        (tmp_path / "a.css").write_bytes(b"body{color:blue}")
        h2 = _compute_build_hash(tmp_path)
        assert h1 != h2

    def test_changes_when_file_renamed(self, tmp_path):
        # Rename with identical bytes must still change the hash,
        # because path is part of the digest input.
        (tmp_path / "a.css").write_bytes(b"same")
        h1 = _compute_build_hash(tmp_path)
        (tmp_path / "a.css").rename(tmp_path / "b.css")
        h2 = _compute_build_hash(tmp_path)
        assert h1 != h2

    def test_excludes_sw_js(self, tmp_path):
        # sw.js contains the hash, so it must not participate in
        # computing the hash (chicken-and-egg).
        (tmp_path / "a.css").write_bytes(b"stable")
        (tmp_path / "sw.js").write_bytes(b"v1")
        h1 = _compute_build_hash(tmp_path)
        (tmp_path / "sw.js").write_bytes(b"v2-different-content")
        h2 = _compute_build_hash(tmp_path)
        assert h1 == h2

    def test_walks_recursively(self, tmp_path):
        sub = tmp_path / "components"
        sub.mkdir()
        (sub / "search.js").write_bytes(b"q()")
        h1 = _compute_build_hash(tmp_path)
        (sub / "search.js").write_bytes(b"q(2)")
        h2 = _compute_build_hash(tmp_path)
        assert h1 != h2

    def test_length_is_12_hex_chars(self, tmp_path):
        (tmp_path / "a.css").write_bytes(b"x")
        h = _compute_build_hash(tmp_path)
        assert len(h) == 12
        int(h, 16)  # raises ValueError if not hex

    def test_raises_on_missing_dir(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _compute_build_hash(tmp_path / "does-not-exist")

    def test_path_order_stable(self, tmp_path):
        # File creation order must not affect hash; sorted paths only.
        (tmp_path / "z.css").write_bytes(b"z")
        (tmp_path / "a.css").write_bytes(b"a")
        h1 = _compute_build_hash(tmp_path)

        other = tmp_path / "other"
        other.mkdir()
        (other / "a.css").write_bytes(b"a")
        (other / "z.css").write_bytes(b"z")
        h2 = _compute_build_hash(other)
        assert h1 == h2


class TestVersionSw:
    def test_replaces_sentinel_line(self, tmp_path):
        sw = tmp_path / "sw.js"
        sw.write_text("const BUILD_VERSION = 'dev';\nconst x = 1;\n")
        _version_sw(tmp_path, "abc123def456")
        assert "const BUILD_VERSION = 'abc123def456';" in sw.read_text()
        assert "const BUILD_VERSION = 'dev';" not in sw.read_text()

    def test_leaves_other_occurrences_of_dev_intact(self, tmp_path):
        sw = tmp_path / "sw.js"
        sw.write_text(
            "// note: use in dev\n"
            "const BUILD_VERSION = 'dev';\n"
            "console.log('dev mode');\n"
        )
        _version_sw(tmp_path, "hash12345678")
        text = sw.read_text()
        assert "// note: use in dev" in text
        assert "console.log('dev mode');" in text
        assert "const BUILD_VERSION = 'hash12345678';" in text

    def test_raises_if_sentinel_absent(self, tmp_path):
        # No fallbacks: if the sentinel isn't there, something is wrong
        # and we must not silently produce a SW without a real version.
        sw = tmp_path / "sw.js"
        sw.write_text("const BUILD_VERSION = 'whatever';\n")
        with pytest.raises(ValueError, match="BUILD_VERSION sentinel"):
            _version_sw(tmp_path, "abc123def456")

    def test_raises_if_sw_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _version_sw(tmp_path, "abc123def456")


class TestBuildSwVersioning:
    def test_sw_sentinel_exists_in_source(self):
        # Source sw.js must carry the exact sentinel so _version_sw
        # has something to replace after copy.
        src = Path(__file__).resolve().parent.parent / "renderer" / "shell-web" / "sw.js"
        assert src.exists(), f"expected source SW at {src}"
        assert "const BUILD_VERSION = 'dev';" in src.read_text()


class TestBuildCacheBusting:
    def test_sw_in_dist_has_real_hash(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        sw_text = (dist / "sw.js").read_text()
        # Sentinel must have been replaced.
        assert "const BUILD_VERSION = 'dev';" not in sw_text
        # And the replacement must be a 12-hex-char hash.
        import re
        m = re.search(r"const BUILD_VERSION = '([0-9a-f]{12})';", sw_text)
        assert m, f"hash line not found in sw.js: {sw_text[:300]}"

    def test_sw_hash_deterministic_across_rebuilds(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist1, _ = build(root, base_url=BASE_URL, crawlable="thin")
        hash1 = _extract_sw_hash((dist1 / "sw.js").read_text())
        # Rebuild without any source changes.
        dist2, _ = build(root, base_url=BASE_URL, crawlable="thin")
        hash2 = _extract_sw_hash((dist2 / "sw.js").read_text())
        assert hash1 == hash2

    def test_sw_hash_changes_when_content_changes(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist1, _ = build(root, base_url=BASE_URL, crawlable="thin")
        hash1 = _extract_sw_hash((dist1 / "sw.js").read_text())

        # Edit a post; HTML output changes → hash must change.
        (root / "posts" / "welcome.md").write_text("""---
title: "Welcome Updated"
slug: welcome
published: true
publish_date: 2026-04-14
excerpt: "Updated."
tags: [test]
---

# Welcome Updated

Different content.
""")
        dist2, _ = build(root, base_url=BASE_URL, crawlable="thin")
        hash2 = _extract_sw_hash((dist2 / "sw.js").read_text())
        assert hash1 != hash2


class TestEncryptedBuild:
    def test_encrypted_post_has_envelope(self, tmp_path):
        """An encrypted post should contain an envelope and gate, not plaintext body."""
        root = _setup_grove(tmp_path)
        posts_dir = root / "posts"
        (posts_dir / "secret.md").write_text("""---
title: "Top Secret"
slug: secret
published: true
encrypted: true
publish_date: 2026-04-14
excerpt: "A secret post."
---

This content should be encrypted and not visible in the HTML.
""")
        dist, mnemonic = build(root, base_url=BASE_URL, encrypted=True, crawlable="thin")
        assert mnemonic is not None
        secret_html = (dist / "secret" / "index.html").read_text()
        assert 'id="grove-envelope"' in secret_html
        assert 'id="grove-gate"' in secret_html
        assert "This content should be encrypted" not in secret_html
        assert "Top Secret" in secret_html  # title stays visible in shell

    def test_unencrypted_post_not_affected(self, tmp_path):
        """When encrypted=True in build, only posts with encrypted: true get envelopes."""
        root = _setup_grove(tmp_path)
        posts_dir = root / "posts"
        (posts_dir / "public.md").write_text("""---
title: "Public Post"
slug: public
published: true
publish_date: 2026-04-14
excerpt: "A public post."
---

This is public content.
""")
        dist, _ = build(root, base_url=BASE_URL, encrypted=True, crawlable="thin")
        public_html = (dist / "public" / "index.html").read_text()
        assert 'id="grove-envelope"' not in public_html
        assert "This is public content" in public_html


class TestBuildImageProcessing:
    def test_build_generates_image_variants(self, tmp_path):
        """Build produces WebP + original variants for images in assets/."""
        from PIL import Image as PILImage

        root = _setup_grove(tmp_path)
        # Add an image to assets
        assets = root / "assets"
        assets.mkdir()
        img = PILImage.new("RGB", (1600, 900), color=(100, 150, 200))
        img.save(assets / "photo.png", "PNG")

        # Add a post referencing the image
        posts_dir = root / "posts"
        (posts_dir / "img-test.md").write_text(
            '---\ntitle: "Image Test"\npublished: true\npublish_date: 2026-04-17\n'
            'excerpt: "Test"\ntags: [test]\n---\n\n![A photo](assets/photo.png)\n',
            encoding="utf-8",
        )

        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")

        # Variants exist
        assert (dist / "assets" / "photo-480w.webp").exists()
        assert (dist / "assets" / "photo-480w.png").exists()
        assert (dist / "assets" / "photo-960w.webp").exists()
        assert (dist / "assets" / "photo-960w.png").exists()
        assert (dist / "assets" / "photo-1440w.webp").exists()
        assert (dist / "assets" / "photo-1440w.png").exists()
        # Original preserved
        assert (dist / "assets" / "photo.png").exists()
        # Manifest written
        assert (dist / "assets" / "image-manifest.json").exists()

    def test_build_without_assets_still_works(self, tmp_path):
        """Build with no assets/ dir produces no manifest, no errors."""
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin")
        assert not (dist / "assets" / "image-manifest.json").exists()


class TestEncryptedBuildImages:
    def test_no_plaintext_images_in_encrypted_build(self, tmp_path):
        """No unencrypted image files in dist/assets/."""
        from PIL import Image as PILImage

        root = _setup_grove(tmp_path)
        assets = root / "assets"
        assets.mkdir()
        img = PILImage.new("RGB", (1600, 900), color=(100, 150, 200))
        img.save(assets / "photo.png", "PNG")

        dist, _ = build(root, base_url=BASE_URL, encrypted=True, crawlable="thin")

        for path in (dist / "assets").rglob("*"):
            if path.is_file():
                assert path.name.endswith(".enc"), f"Plaintext file leaked: {path.name}"

    def test_enc_files_exist_for_variants(self, tmp_path):
        """Encrypted build produces .enc files for original + variants."""
        from PIL import Image as PILImage

        root = _setup_grove(tmp_path)
        assets = root / "assets"
        assets.mkdir()
        img = PILImage.new("RGB", (1600, 900), color=(100, 150, 200))
        img.save(assets / "photo.png", "PNG")

        dist, _ = build(root, base_url=BASE_URL, encrypted=True, crawlable="thin")

        assert (dist / "assets" / "photo.png.enc").exists()
        assert (dist / "assets" / "photo-480w.webp.enc").exists()
        assert (dist / "assets" / "photo-480w.png.enc").exists()

    def test_enc_files_are_valid_envelopes(self, tmp_path):
        """Each .enc file is a valid JSON envelope."""
        from PIL import Image as PILImage

        root = _setup_grove(tmp_path)
        assets = root / "assets"
        assets.mkdir()
        img = PILImage.new("RGB", (800, 600), color=(50, 100, 150))
        img.save(assets / "small.png", "PNG")

        dist, _ = build(root, base_url=BASE_URL, encrypted=True, crawlable="thin")

        enc_path = dist / "assets" / "small.png.enc"
        assert enc_path.exists()
        envelope = json.loads(enc_path.read_text())
        assert envelope["encrypted"] is True
        assert "salt" in envelope
        assert "iv" in envelope
        assert "payload" in envelope

    def test_all_enc_files_share_same_salt(self, tmp_path):
        """All encrypted assets use the same salt for single key derivation."""
        from PIL import Image as PILImage

        root = _setup_grove(tmp_path)
        assets = root / "assets"
        assets.mkdir()
        img = PILImage.new("RGB", (1600, 900), color=(100, 150, 200))
        img.save(assets / "photo.png", "PNG")

        dist, _ = build(root, base_url=BASE_URL, encrypted=True, crawlable="thin")

        salts = set()
        for path in (dist / "assets").rglob("*.enc"):
            envelope = json.loads(path.read_text())
            salts.add(envelope["salt"])
        assert len(salts) == 1, f"Expected 1 shared salt, got {len(salts)}"

    def test_roundtrip_decrypt_image(self, tmp_path):
        """Encrypted image decrypts back to original bytes."""
        import base64
        from PIL import Image as PILImage
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes

        root = _setup_grove(tmp_path)
        assets = root / "assets"
        assets.mkdir()
        img = PILImage.new("RGB", (800, 600), color=(50, 100, 150))
        img.save(assets / "test.png", "PNG")
        original_bytes = (assets / "test.png").read_bytes()

        dist, mnemonic = build(root, base_url=BASE_URL, encrypted=True, crawlable="thin")

        envelope = json.loads((dist / "assets" / "test.png.enc").read_text())
        salt = base64.b64decode(envelope["salt"])
        iv = base64.b64decode(envelope["iv"])
        ct = base64.b64decode(envelope["payload"])
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                         salt=salt, iterations=100000)
        key = kdf.derive(mnemonic.encode())
        assert AESGCM(key).decrypt(iv, ct, None) == original_bytes

    def test_bundle_contains_asset_manifest(self, tmp_path):
        """Decrypted bundle.enc includes assetManifest with image entries."""
        import base64
        from PIL import Image as PILImage
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes

        root = _setup_grove(tmp_path)
        assets = root / "assets"
        assets.mkdir()
        img = PILImage.new("RGB", (1600, 900), color=(100, 150, 200))
        img.save(assets / "photo.png", "PNG")

        posts_dir = root / "posts"
        (posts_dir / "img-post.md").write_text(
            '---\ntitle: "Image Post"\npublished: true\npublish_date: 2026-04-17\n'
            'excerpt: "Has image"\ntags: [test]\n---\n\n![Photo](assets/photo.png)\n'
        )

        dist, mnemonic = build(root, base_url=BASE_URL, encrypted=True, crawlable="thin")

        envelope = json.loads((dist / "bundle.enc").read_text())
        salt = base64.b64decode(envelope["salt"])
        iv = base64.b64decode(envelope["iv"])
        ct = base64.b64decode(envelope["payload"])
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                         salt=salt, iterations=100000)
        key = kdf.derive(mnemonic.encode())
        bundle = json.loads(AESGCM(key).decrypt(iv, ct, None).decode())
        assert "assetManifest" in bundle
        assert "assets/photo.png" in bundle["assetManifest"]
        assert "assetSalt" in bundle

    def test_encrypted_build_no_assets_works(self, tmp_path):
        """Encrypted build without assets/ produces valid output."""
        root = _setup_grove(tmp_path)
        dist, mnemonic = build(root, base_url=BASE_URL, encrypted=True, crawlable="thin")
        assert dist.exists()
        assert (dist / "bundle.enc").exists()
        assert mnemonic is not None

    def test_encrypted_sw_has_empty_owned_assets(self, tmp_path):
        """Encrypted build must not leak image paths in sw.js OWNED_ASSETS."""
        from PIL import Image as PILImage

        root = _setup_grove(tmp_path)
        assets = root / "assets"
        assets.mkdir()
        img = PILImage.new("RGB", (1600, 900), color=(100, 150, 200))
        img.save(assets / "photo.png", "PNG")

        dist, _ = build(root, base_url=BASE_URL, encrypted=True, crawlable="thin")

        sw_text = (dist / "sw.js").read_text()
        assert "const OWNED_ASSETS = [];" in sw_text, (
            f"Encrypted SW must have empty OWNED_ASSETS, got: "
            f"{[l for l in sw_text.splitlines() if 'OWNED_ASSETS' in l]}"
        )


class TestLocalFirstBuild:
    def test_local_first_creates_manifest(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        assert (dist / "manifest.json").exists()

    def test_local_first_creates_blobs_dir(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        blobs_dir = dist / "blobs"
        assert blobs_dir.is_dir()
        bin_files = list(blobs_dir.glob("*.bin"))
        assert len(bin_files) > 0

    def test_local_first_creates_app_shell(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        index_html = (dist / "index.html").read_text()
        assert "grove-base-path" in index_html

    def test_local_first_creates_og_pages(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        og_page = dist / "welcome" / "index.html"
        assert og_page.exists()
        html = og_page.read_text()
        assert "og:title" in html
        assert "site-header" in html  # full app shell, not bare stub
        assert "http-equiv" not in html  # no meta-refresh

    def test_local_first_manifest_has_entries(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        manifest = json.loads((dist / "manifest.json").read_text())
        routes = [e["route"] for e in manifest["entries"]]
        assert "/" in routes
        assert "/welcome/" in routes

    def test_local_first_draft_excluded_from_manifest(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        manifest = json.loads((dist / "manifest.json").read_text())
        routes = [e["route"] for e in manifest["entries"]]
        assert "/draft/" not in routes

    def test_local_first_still_generates_feeds(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        assert (dist / "feed.xml").exists()

    def test_local_first_manifest_entry_has_metadata(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        manifest = json.loads((dist / "manifest.json").read_text())
        welcome = [e for e in manifest["entries"] if e["route"] == "/welcome/"]
        assert len(welcome) == 1
        entry = welcome[0]
        assert "title" in entry
        assert "excerpt" in entry
        assert "blob" in entry
        assert "hash" in entry
        assert "priority" in entry

    def test_local_first_blobs_are_content_addressed(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        manifest = json.loads((dist / "manifest.json").read_text())
        for entry in manifest["entries"]:
            blob_path = dist / "blobs" / entry["blob"]
            assert blob_path.exists(), f"Blob missing for route {entry['route']}: {entry['blob']}"

    def test_local_first_og_page_is_app_shell(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        og_html = (dist / "welcome" / "index.html").read_text()
        assert "og:title" in og_html
        assert "site-header" in og_html
        assert "app.js" in og_html
        assert "http-equiv" not in og_html  # no meta-refresh

    def test_local_first_blobs_are_fragments_not_full_pages(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        manifest = json.loads((dist / "manifest.json").read_text())
        for entry in manifest["entries"]:
            blob_path = dist / "blobs" / entry["blob"]
            content = blob_path.read_text(encoding="utf-8")
            assert "<!DOCTYPE" not in content, f"Blob for {entry['route']} is a full page"
            assert "<html" not in content
            assert "site-header" not in content
            assert "site-footer" not in content

    def test_local_first_manifest_entries_have_layout(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")
        manifest = json.loads((dist / "manifest.json").read_text())
        for entry in manifest["entries"]:
            assert "layout" in entry, f"Missing layout for {entry['route']}"

    def test_local_first_manifest_has_image_assets(self, tmp_path):
        """Local-first manifest.assets contains entries for all generated image variants."""
        from PIL import Image as PILImage

        root = _setup_grove(tmp_path)
        assets = root / "assets"
        assets.mkdir()
        img = PILImage.new("RGB", (1600, 900), color=(100, 150, 200))
        img.save(assets / "photo.png", "PNG")

        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")

        manifest = json.loads((dist / "manifest.json").read_text())
        assert len(manifest["assets"]) > 0, "manifest.assets should contain image entries"

        paths = [a["path"] for a in manifest["assets"]]
        # Original
        assert "assets/photo.png" in paths
        # At least one variant (1600px source generates 480w, 960w, 1440w)
        assert any("photo-" in p and "w." in p for p in paths), (
            f"Expected sized variants in manifest.assets, got: {paths}"
        )
        # Every entry has required fields and valid MIME
        for asset in manifest["assets"]:
            assert "path" in asset
            assert "mime" in asset
            assert asset["mime"].startswith("image/"), (
                f"Expected image MIME for {asset['path']}, got {asset['mime']}"
            )

    def test_local_first_manifest_only_generated_variants(self, tmp_path):
        """Image smaller than 960px should not have 960w or 1440w variants."""
        from PIL import Image as PILImage

        root = _setup_grove(tmp_path)
        assets = root / "assets"
        assets.mkdir()
        # 400px wide — only 480w threshold is skipped (400 < 480), so no variants
        img = PILImage.new("RGB", (400, 300), color=(50, 100, 150))
        img.save(assets / "small.png", "PNG")

        dist, _ = build(root, base_url=BASE_URL, local_first=True, crawlable="thin")

        manifest = json.loads((dist / "manifest.json").read_text())
        paths = [a["path"] for a in manifest["assets"]]

        # Original should be present
        assert "assets/small.png" in paths
        # No sized variants — 400px is smaller than all thresholds (480, 960, 1440)
        variant_paths = [p for p in paths if "small-" in p]
        assert len(variant_paths) == 0, (
            f"400px image should have no sized variants, got: {variant_paths}"
        )

    def test_local_first_writes_404_app_shell(self, tmp_path):
        root = _setup_grove(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="full", local_first=True,
                        service_worker=False)
        assert (dist / "404.html").is_file()
        assert 'name="grove-base-path"' in (dist / "404.html").read_text()  # it's the app shell


def test_theme_style_css_reaches_page(tmp_path):
    """The theme's structural style.css is inlined into the built page.

    [data-theme="default"] is emitted ONLY by the appended style.css stub,
    never by the token resolver — so finding it proves the wiring.
    """
    root = _setup_grove(tmp_path)
    dist, _ = build(root, base_url=BASE_URL, crawlable="thin")

    index_html = (dist / "index.html").read_text()
    assert '[data-theme="default"]' in index_html


def _setup_grove_with_pages(tmp_path):
    (tmp_path / "grove.yaml").write_text(
        'id: g\ntitle: "Test Grove"\nlang: en\n'
        'description: "d"\n'
        'og:\n  title: T\n  description: d\n  image: og.png\n'
        'defaults:\n  view: grid\n  layout: article\n  posts_per_page: 10\n'
        'header:\n  actions: []\n'
        'rss:\n  enabled: true\n  max_items: 10\n'
        'features:\n  - id: assistant\n    type: chat\n    ask: faq\n'
        'pages:\n  "/landing": pages/landing\n  "/chatbot": pages/chatbot\n'
    )
    posts = tmp_path / "posts"; posts.mkdir()
    (posts / "welcome.md").write_text(
        '---\ntitle: "Welcome"\nslug: welcome\npublished: true\n'
        'publish_date: 2026-04-14\nexcerpt: "Hi."\n---\n# Welcome\nHi.')
    land = tmp_path / "pages" / "landing"; land.mkdir(parents=True)
    (land / "page.yaml").write_text('title: "Landing"\nlayout: landing\n')
    (land / "index.html").write_text('<section class="hero"><h1>Own your data</h1></section>')
    (land / "styles.css").write_text('.hero h1 { color: red; }')
    chat = tmp_path / "pages" / "chatbot"; chat.mkdir(parents=True)
    (chat / "page.yaml").write_text('title: "Chatbot"\nbody:\n  - feature: assistant\n')
    return tmp_path


class TestPagesInBuild:
    def test_bare_grove_default_home(self, tmp_path):
        (tmp_path / "grove.yaml").write_text(
            'id: g\ntitle: "Bare"\nlang: en\ndescription: "d"\n'
            'og:\n  title: T\n  description: d\n  image: og.png\n'
            'defaults:\n  view: grid\n  layout: article\n  posts_per_page: 10\n'
            'header:\n  actions: []\nrss:\n  enabled: true\n  max_items: 10\n')
        posts = tmp_path / "posts"; posts.mkdir()
        (posts / "welcome.md").write_text(
            '---\ntitle: "Welcome"\nslug: welcome\npublished: true\n'
            'publish_date: 2026-04-14\nexcerpt: "Hi."\n---\n# Welcome\nHi.')
        dist, _ = build(tmp_path, base_url=BASE_URL, crawlable="thin")
        index = (dist / "index.html").read_text()
        assert "feed-grid" in index and "Welcome" in index

    def test_landing_and_chatbot_pages_built(self, tmp_path):
        root = _setup_grove_with_pages(tmp_path)
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin",
                        feature_endpoints={"assistant": "https://ask.example.com"})
        land = (dist / "landing" / "index.html").read_text()
        assert "Own your data" in land and "data-p-" in land and "<header" not in land
        chat = (dist / "chatbot" / "index.html").read_text()
        assert "data-chat-root" in chat and "connect-src https://ask.example.com" in chat
        # bare home still rendered (no "/" page declared)
        assert "feed-grid" in (dist / "index.html").read_text()

    def test_custom_home_overrides_feed(self, tmp_path):
        root = _setup_grove_with_pages(tmp_path)
        import yaml as _y
        gp = root / "grove.yaml"; g = _y.safe_load(gp.read_text())
        g["pages"]["/"] = "pages/index"; gp.write_text(_y.safe_dump(g))
        idx = root / "pages" / "index"; idx.mkdir(parents=True)
        (idx / "page.yaml").write_text('title: Home\nbody:\n  - self\n')
        (idx / "index.html").write_text('<section>CUSTOM HOME MARKER</section>')
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin",
                        feature_endpoints={"assistant": "https://ask.example.com"})
        assert "CUSTOM HOME MARKER" in (dist / "index.html").read_text()

    def test_page_post_route_collision_raises(self, tmp_path):
        root = _setup_grove_with_pages(tmp_path)
        # add a page whose route equals the existing post's url_path (/welcome/)
        import yaml as _y
        gp = root / "grove.yaml"; g = _y.safe_load(gp.read_text())
        g["pages"]["/welcome"] = "pages/welcome"; gp.write_text(_y.safe_dump(g))
        wf = root / "pages" / "welcome"; wf.mkdir(parents=True)
        (wf / "page.yaml").write_text('title: W\nbody: [grid]\n')
        import pytest
        with pytest.raises(Exception, match="collides"):
            build(root, base_url=BASE_URL, crawlable="thin",
                  feature_endpoints={"assistant": "https://ask.example.com"})

    def test_unpublished_page_not_rendered(self, tmp_path):
        root = _setup_grove_with_pages(tmp_path)
        import yaml as _y
        gp = root / "grove.yaml"; g = _y.safe_load(gp.read_text())
        g["pages"]["/draft"] = "pages/draft"; gp.write_text(_y.safe_dump(g))
        d = root / "pages" / "draft"; d.mkdir(parents=True)
        (d / "page.yaml").write_text('title: Draft\npublished: false\nbody: [grid]\n')
        dist, _ = build(root, base_url=BASE_URL, crawlable="thin",
                        feature_endpoints={"assistant": "https://ask.example.com"})
        assert not (dist / "draft" / "index.html").exists()


def _extract_sw_hash(sw_text: str) -> str:
    import re
    m = re.search(r"const BUILD_VERSION = '([0-9a-f]{12})';", sw_text)
    assert m, "sw.js does not contain a hashed BUILD_VERSION line"
    return m.group(1)


def test_local_first_emits_declared_chat_page(tmp_path):
    root = _setup_grove(tmp_path)
    # add a chat feature + /ghost page to the grove
    import yaml
    g = yaml.safe_load((root / "grove.yaml").read_text())
    g["features"] = [{"type": "chat", "id": "ghost", "ask": "write", "persist": "local"}]
    g["pages"] = {"/ghost": "pages/ghost"}
    (root / "grove.yaml").write_text(yaml.dump(g))
    (root / "pages" / "ghost").mkdir(parents=True)
    (root / "pages" / "ghost" / "page.yaml").write_text(
        yaml.dump({"title": "Ghostwriter", "mount": "subtree", "layout": "minimal",
                   "body": [{"feature": "ghost"}]}))
    dist, _ = build(root, base_url=BASE_URL, crawlable="full", local_first=True,
                    service_worker=False,
                    feature_endpoints={"ghost": "https://ask.moui.co"},
                    chat_config={"endpoint": "https://ask.moui.co/api",
                                 "gate": {"scheme": "access-code",
                                          "check": "https://ask.moui.co/api/check"}})
    assert (dist / "ghost" / "index.html").is_file(), "local-first dropped the declared chat page"


def test_local_first_app_shell_has_island_and_csp(tmp_path):
    root = _setup_grove(tmp_path)
    import yaml, re, json
    g = yaml.safe_load((root / "grove.yaml").read_text())
    g["features"] = [{"type": "chat", "id": "ghost", "ask": "write", "persist": "local"}]
    g["pages"] = {"/ghost": "pages/ghost"}
    (root / "grove.yaml").write_text(yaml.dump(g))
    (root / "pages" / "ghost").mkdir(parents=True)
    (root / "pages" / "ghost" / "page.yaml").write_text(
        yaml.dump({"title": "Ghostwriter", "mount": "subtree", "layout": "minimal",
                   "body": [{"feature": "ghost"}]}))
    dist, _ = build(root, base_url=BASE_URL, crawlable="full", local_first=True,
                    service_worker=False,
                    feature_endpoints={"ghost": "https://ask.moui.co"},
                    chat_config={"endpoint": "https://ask.moui.co/api",
                                 "gate": {"scheme": "access-code",
                                          "check": "https://ask.moui.co/api/check"}})
    ghost = (dist / "ghost" / "index.html").read_text()
    m = re.search(r'id="chat-config">(\{.*?\})</script>', ghost, re.S)
    assert m and json.loads(m.group(1))["gate"]["check"] == "https://ask.moui.co/api/check"
    assert "connect-src 'self' https://ask.moui.co" in ghost


def test_font_urls_root_absolute_at_root_deploy(tmp_path):
    # Build a grove with a real font fixture so build_fonts_css emits @font-face CSS.
    # At root deploy (base_url has no subpath), the emitted src must use /fonts/...
    # (root-absolute), not fonts/... (bare relative). A bare relative URL on a
    # subpath page (/ghost/) would resolve as /ghost/fonts/... → 404.
    import shutil

    root = _setup_grove(tmp_path)

    # Minimal theme tree: copy the shape's default theme, then add a font file.
    shape_themes = Path(__file__).resolve().parent.parent / "themes"
    custom_themes = tmp_path / "themes"
    shutil.copytree(shape_themes, custom_themes)
    font_dir = custom_themes / "default" / "fonts" / "Lato"
    font_dir.mkdir(parents=True)
    (font_dir / "Lato-Regular.woff2").write_bytes(b"WOFF2FAKE")

    # Point grove at the custom theme dir.
    import yaml as _yaml
    g = _yaml.safe_load((root / "grove.yaml").read_text())
    g["theme"] = "themes"
    (root / "grove.yaml").write_text(_yaml.dump(g))

    dist, _ = build(root, base_url="https://www.moui.io/", crawlable="full",
                    local_first=False, service_worker=False)
    # fonts_css is inlined in <style id="grove-tokens"> in every page — check index.html.
    html = (dist / "index.html").read_text()
    # @font-face must have been emitted — otherwise the test is vacuous.
    assert "@font-face" in html, "font fixture must produce @font-face output in index.html"
    # The src must be root-absolute: url('/fonts/...')  not bare url('fonts/...')
    assert "url('fonts/" not in html and 'url("fonts/' not in html, (
        "font src must not be bare relative — subpath pages would resolve it wrong"
    )


def test_chat_grove_rejects_missing_gate_strings(tmp_path):
    """A chat grove whose theme lacks the secret-gate/ask-state strings must fail the build.

    Behavioral: exercises the _feature_required_strings → load_strings → MissingStringsError
    contract. Uses a custom theme that carries all current strings but omits the six new keys.
    The test is RED before CHAT_STRING_KEYS includes those keys (build succeeds when it
    shouldn't) and GREEN after (build raises as required).
    """
    import shutil, yaml
    from strings import MissingStringsError

    root = _setup_grove(tmp_path)

    # Custom theme: copy shape default, then REMOVE the new gate/ask-state keys.
    shape_themes = Path(__file__).resolve().parent.parent / "themes"
    custom_themes = tmp_path / "themes"
    shutil.copytree(shape_themes, custom_themes)
    strings_path = custom_themes / "default" / "strings.yaml"
    existing = yaml.safe_load(strings_path.read_text())
    for k in ("chat_gate_prompt", "chat_gate_submit", "chat_gate_rejected", "chat_over_limit",
              "chat_revoked", "chat_offline", "chat_unavailable", "chat_not_permitted"):
        existing.pop(k, None)          # pop to tolerate if already absent
    strings_path.write_text(yaml.safe_dump(existing))

    # Point grove at the custom theme and declare a chat feature.
    g = yaml.safe_load((root / "grove.yaml").read_text())
    g["theme"] = "themes"
    g["features"] = [{"type": "chat", "id": "asst", "ask": "faq"}]
    (root / "grove.yaml").write_text(yaml.safe_dump(g))

    with pytest.raises(MissingStringsError) as exc_info:
        build(root, base_url=BASE_URL, crawlable="thin",
              chat_config={"endpoint": "https://ask.example.com/api",
                           "gate": {"scheme": "access-code",
                                    "check": "https://ask.example.com/api/check"}})

    missing = set(exc_info.value.missing_keys)
    for k in ("chat_gate_prompt", "chat_gate_submit", "chat_gate_rejected", "chat_over_limit",
              "chat_revoked", "chat_offline", "chat_unavailable", "chat_not_permitted"):
        assert k in missing, f"expected MissingStringsError to name '{k}'"


def test_chat_not_permitted_is_required():
    from build import CHAT_STRING_KEYS
    assert "chat_not_permitted" in CHAT_STRING_KEYS


def test_chat_attach_strings_are_required():
    from build import CHAT_STRING_KEYS
    for key in ("chat_attach", "chat_attach_remove", "chat_attach_too_large",
                "chat_attach_wrong_type", "chat_attach_too_many", "chat_attach_failed",
                "chat_attach_missing", "chat_attach_not_saved", "chat_attach_unavailable"):
        assert key in CHAT_STRING_KEYS, f"{key} must be a required chat string"


def test_chat_config_carries_grove_key(tmp_path):
    # the emitted #chat-config blob includes grove_key = the grove's base_path,
    # so the client can hold the secret per-grove (single entry) not per-route.
    import json, re
    from chat_config import emit_chat_config
    grove = {"features": [{"type": "chat", "id": "a", "ask": "converse", "route": "/x"}]}
    ctx = {"base_path": "/hub"}
    html = emit_chat_config(grove, [], ctx, endpoint="https://b", gate=None)
    blob = json.loads(re.search(r'id="chat-config">(\{.*?\})</script>', html, re.S).group(1))
    assert blob["grove_key"] == "/hub"


def test_renderer_assets_ship_without_tests_or_test_shims(tmp_path):
    from build import _copy_renderer_assets
    shape = Path(__file__).resolve().parent.parent          # shapes/grove
    _copy_renderer_assets(tmp_path, shape)
    shipped = [p.name for p in tmp_path.rglob("*") if p.is_file()]
    assert "chat.js" in shipped, "the real components ship"
    assert not [n for n in shipped if n.startswith("test_")], "tests do not ship"
    assert not [n for n in shipped if n.startswith("_") and n.endswith(".mjs")], "test shims do not ship"
