"""Tests for grove init frontmatter generation."""
from datetime import date
from pathlib import Path

import pytest

from init_post import discover_layouts, discover_sections, generate_frontmatter, has_frontmatter, init_file


def test_generates_title_from_filename():
    result = generate_frontmatter(
        filename="my-new-post.md",
        today=date(2026, 4, 19),
        sections=["architecture", "tutorials"],
        layouts=["article", "quote", "landing", "minimal"],
        lang="en",
    )
    assert result.startswith("---\n")
    assert result.endswith("\n---\n")
    assert 'title: "My New Post"' in result


def test_title_strips_md_extension():
    result = generate_frontmatter(
        filename="cloud-act.md",
        today=date(2026, 4, 19),
        sections=[],
        layouts=["article"],
        lang="en",
    )
    assert 'title: "Cloud Act"' in result


def test_published_defaults_to_true():
    result = generate_frontmatter(
        filename="test.md",
        today=date(2026, 4, 19),
        sections=[],
        layouts=["article"],
        lang="en",
    )
    assert "published: true" in result


def test_optional_fields_are_commented():
    result = generate_frontmatter(
        filename="test.md",
        today=date(2026, 4, 19),
        sections=[],
        layouts=["article"],
        lang="en",
    )
    assert "# slug:" in result
    assert "publish_date: 2026-04-19" in result
    assert 'excerpt: "Test"' in result
    assert "# tags:" in result
    assert "# featured:" in result
    assert "# weight:" in result
    assert "# layout:" in result
    assert "# theme:" in result
    assert "# og:" in result
    assert "# related:" in result


def test_sections_from_grove_directory():
    result = generate_frontmatter(
        filename="test.md",
        today=date(2026, 4, 19),
        sections=["architecture", "use-cases", "tutorials"],
        layouts=["article"],
        lang="en",
    )
    assert "# section:" in result
    assert "architecture | use-cases | tutorials" in result


def test_sections_empty_shows_empty_string():
    result = generate_frontmatter(
        filename="test.md",
        today=date(2026, 4, 19),
        sections=[],
        layouts=["article"],
        lang="en",
    )
    assert '# section: ""' in result


def test_layouts_from_shape():
    result = generate_frontmatter(
        filename="test.md",
        today=date(2026, 4, 19),
        sections=[],
        layouts=["article", "quote", "landing", "minimal"],
        lang="en",
    )
    assert "# layout: article" in result
    assert "article | quote | landing | minimal" in result


def test_lang_from_grove():
    result = generate_frontmatter(
        filename="test.md",
        today=date(2026, 4, 19),
        sections=[],
        layouts=["article"],
        lang="de",
    )
    assert "# lang: de" in result


def test_translations_section_present():
    result = generate_frontmatter(
        filename="test.md",
        today=date(2026, 4, 19),
        sections=[],
        layouts=["article"],
        lang="en",
    )
    assert "# translations:" in result


def test_discover_sections_from_directories(tmp_path):
    posts = tmp_path / "posts"
    posts.mkdir(parents=True)
    (posts / "architecture").mkdir()
    (posts / "tutorials").mkdir()
    # files should not appear as sections
    (posts / "welcome.md").write_text("hello")

    result = discover_sections(tmp_path)
    assert sorted(result) == ["architecture", "tutorials"]


def test_discover_sections_empty_when_no_subdirs(tmp_path):
    posts = tmp_path / "posts"
    posts.mkdir(parents=True)
    assert discover_sections(tmp_path) == []


def test_discover_sections_raises_when_no_posts_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_sections(tmp_path)


def test_discover_layouts():
    result = discover_layouts(Path(__file__).resolve().parents[1])
    assert "article" in result
    assert "quote" in result
    assert "landing" in result
    assert "minimal" in result


def test_has_frontmatter_true():
    assert has_frontmatter("---\ntitle: X\n---\nbody") is True


def test_has_frontmatter_false_empty():
    assert has_frontmatter("") is False


def test_has_frontmatter_false_no_delimiters():
    assert has_frontmatter("just some text") is False


def test_has_frontmatter_false_partial():
    assert has_frontmatter("---\ntitle: X\nno closing") is False


def test_init_file_adds_frontmatter(tmp_path):
    md = tmp_path / "my-post.md"
    md.write_text("Some content here.\n")

    changed = init_file(
        path=md,
        today=date(2026, 4, 19),
        sections=["architecture"],
        layouts=["article", "quote"],
        lang="en",
    )
    assert changed is True

    text = md.read_text()
    assert text.startswith("---\n")
    assert 'title: "My Post"' in text
    assert "Some content here." in text


def test_init_file_skips_existing_frontmatter(tmp_path):
    md = tmp_path / "existing.md"
    original = "---\ntitle: Already Here\n---\nbody text"
    md.write_text(original)

    changed = init_file(
        path=md,
        today=date(2026, 4, 19),
        sections=[],
        layouts=["article"],
        lang="en",
    )
    assert changed is False
    assert md.read_text() == original


def test_init_file_preserves_body(tmp_path):
    md = tmp_path / "has-body.md"
    md.write_text("# My heading\n\nParagraph text.\n")

    init_file(
        path=md,
        today=date(2026, 4, 19),
        sections=[],
        layouts=["article"],
        lang="en",
    )
    text = md.read_text()
    assert "# My heading" in text
    assert "Paragraph text." in text
    assert text.index("---") < text.index("# My heading")


def test_template_uses_named_related_and_no_fallback_wording():
    from init_post import generate_frontmatter
    from datetime import date
    fm = generate_frontmatter(filename="my-post.md", today=date(2026, 6, 17),
                              sections=[], layouts=["article", "landing"], lang="en")
    assert "related: auto" in fm
    assert "fallback" not in fm
