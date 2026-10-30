import json
import pytest
from pathlib import Path
from pages import load_pages, PageError


def _grove(pages):
    return {"title": "Test Grove", "pages": pages}


def _folder(tmp, rel, page_yaml=None, index_html=None):
    d = Path(tmp) / rel
    d.mkdir(parents=True, exist_ok=True)
    if page_yaml is not None:
        (d / "page.yaml").write_text(page_yaml, encoding="utf-8")
    if index_html is not None:
        (d / "index.html").write_text(index_html, encoding="utf-8")
    return d


class TestLoadPages:
    def test_absent_map_returns_empty(self, tmp_path):
        assert load_pages(tmp_path, {"title": "G"}) == []

    def test_loads_declared_folder(self, tmp_path):
        _folder(tmp_path, "pages/manifiesto",
                page_yaml='title: "Manifiesto"\nlayout: landing\n',
                index_html="<section>hi</section>")
        pages = load_pages(tmp_path, _grove({"/manifiesto": "pages/manifiesto"}))
        assert len(pages) == 1
        p = pages[0]
        assert p["route"] == "/manifiesto"
        assert p["title"] == "Manifiesto"
        assert p["layout"] == "landing"
        assert p["body"] == ["self"]
        assert p["folder"].name == "manifiesto"

    def test_explicit_body(self, tmp_path):
        _folder(tmp_path, "pages/index", page_yaml='title: Home\nbody:\n  - elements/hero\n  - grid: {limit: 6}\n')
        pages = load_pages(tmp_path, _grove({"/": "pages/index"}))
        assert pages[0]["body"] == ["elements/hero", {"grid": {"limit": 6}}]

    def test_home_title_defaults_to_grove_title(self, tmp_path):
        _folder(tmp_path, "pages/index", page_yaml='body: [grid]\n')
        pages = load_pages(tmp_path, _grove({"/": "pages/index"}))
        assert pages[0]["title"] == "Test Grove"

    def test_missing_folder_throws(self, tmp_path):
        with pytest.raises(PageError, match="folder"):
            load_pages(tmp_path, _grove({"/x": "pages/nope"}))

    def test_missing_page_yaml_throws(self, tmp_path):
        _folder(tmp_path, "pages/x")
        with pytest.raises(PageError, match="page.yaml"):
            load_pages(tmp_path, _grove({"/x": "pages/x"}))

    def test_missing_title_throws_for_non_home(self, tmp_path):
        _folder(tmp_path, "pages/x", page_yaml='body: [grid]\n')
        with pytest.raises(PageError, match="title"):
            load_pages(tmp_path, _grove({"/x": "pages/x"}))

    def test_published_false_carried(self, tmp_path):
        _folder(tmp_path, "pages/x", page_yaml='title: X\npublished: false\nbody: [grid]\n')
        assert load_pages(tmp_path, _grove({"/x": "pages/x"}))[0]["published"] is False


def test_page_schema_has_no_slug_requires_title():
    schema = json.loads((Path(__file__).resolve().parent.parent / "schemas" / "page.v1.json").read_text())
    assert schema["required"] == ["title"]
    assert "slug" not in schema["properties"]
    assert "body" in schema["properties"]
