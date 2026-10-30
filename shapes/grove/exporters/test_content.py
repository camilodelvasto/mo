"""Tests for grove content loader."""
import pytest
from pathlib import Path
from content import load_post, scan_posts, ParseError

def _write_post(tmp, rel_path, frontmatter, body="Hello."):
    p = Path(tmp) / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{frontmatter}\n---\n\n{body}")
    return p

class TestLoadPost:
    def test_parses_frontmatter_and_body(self, tmp_path):
        p = _write_post(tmp_path, "welcome.md",
            'title: "Welcome"\nslug: welcome\npublished: true\npublish_date: 2026-04-14')
        post = load_post(p)
        assert post["title"] == "Welcome"
        assert post["slug"] == "welcome"
        assert post["published"] is True
        assert "Hello." in post["body"]

    def test_missing_title_throws(self, tmp_path):
        p = _write_post(tmp_path, "bad.md", 'slug: bad\npublished: true')
        with pytest.raises(ParseError, match="title"):
            load_post(p)

    def test_empty_frontmatter_throws(self, tmp_path):
        p = Path(tmp_path) / "empty.md"
        p.write_text("No frontmatter here")
        with pytest.raises(ParseError):
            load_post(p)

class TestScanPosts:
    def test_finds_nested_posts(self, tmp_path):
        _write_post(tmp_path, "welcome.md",
            'title: "Welcome"\nslug: welcome\npublished: true\npublish_date: 2026-04-14')
        _write_post(tmp_path, "architecture/corpus-format.md",
            'title: "Corpus Format"\npublished: true\npublish_date: 2026-04-14')
        posts = scan_posts(tmp_path)
        assert len(posts) == 2
        paths = {p["content_path"] for p in posts}
        assert "welcome" in paths
        assert "architecture/corpus-format" in paths

    def test_skips_non_markdown(self, tmp_path):
        _write_post(tmp_path, "post.md",
            'title: "Post"\npublished: true\npublish_date: 2026-04-14')
        (tmp_path / "notes.txt").write_text("not a post")
        posts = scan_posts(tmp_path)
        assert len(posts) == 1

    def test_index_md_becomes_section(self, tmp_path):
        _write_post(tmp_path, "architecture/index.md",
            'title: "Architecture"\npublished: true\npublish_date: 2026-04-14')
        posts = scan_posts(tmp_path)
        assert posts[0]["content_path"] == "architecture"
        assert posts[0]["is_section_index"] is True

class TestBooleanNormalization:
    def test_encrypted_defaults_false(self, tmp_path):
        p = _write_post(tmp_path, "plain.md",
            'title: "Plain"\nslug: plain\npublished: true\npublish_date: 2026-04-14')
        post = load_post(p)
        assert post["encrypted"] is False
        assert post["unlisted"] is False

    def test_encrypted_true_preserved(self, tmp_path):
        p = _write_post(tmp_path, "secret.md",
            'title: "Secret"\nslug: secret\npublished: true\nencrypted: true\npublish_date: 2026-04-14')
        post = load_post(p)
        assert post["encrypted"] is True

    def test_unlisted_true_preserved(self, tmp_path):
        p = _write_post(tmp_path, "hidden.md",
            'title: "Hidden"\nslug: hidden\npublished: true\nunlisted: true\npublish_date: 2026-04-14')
        post = load_post(p)
        assert post["unlisted"] is True
