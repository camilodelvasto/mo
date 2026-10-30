"""Tests for TOC extraction."""
from toc import extract_toc

class TestExtractToc:
    def test_extracts_headings(self):
        html = '<h2 id="intro">Introduction</h2><p>Text.</p><h2 id="setup">Setup</h2>'
        toc = extract_toc(html)
        assert len(toc) == 2
        assert toc[0]["text"] == "Introduction"
        assert toc[0]["id"] == "intro"
        assert toc[0]["level"] == 2

    def test_nested_headings(self):
        html = '<h2 id="a">A</h2><h3 id="b">B</h3><h2 id="c">C</h2>'
        toc = extract_toc(html)
        assert len(toc) == 3
        assert toc[1]["level"] == 3

    def test_empty_html(self):
        assert extract_toc("") == []
        assert extract_toc("<p>No headings</p>") == []

    def test_generates_ids_when_missing(self):
        html = '<h2>No ID Here</h2>'
        toc = extract_toc(html)
        assert toc[0]["id"] == "no-id-here"

    def test_skips_h1(self):
        html = '<h1>Title</h1><h2 id="a">Section</h2>'
        toc = extract_toc(html)
        assert len(toc) == 1
        assert toc[0]["text"] == "Section"
