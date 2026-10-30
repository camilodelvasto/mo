"""Tests for grove visibility filter."""
from visibility import (filter_for_build, filter_for_index, filter_for_feed,
                         filter_for_sitemap, filter_for_search,
                         filter_for_serve_build, filter_for_serve_index)

def _post(published=True, unlisted=False, encrypted=False, **kw):
    return {"title": "T", "published": published, "unlisted": unlisted,
            "encrypted": encrypted, "content_path": "test", "url_path": "/test/", **kw}

class TestFilterForBuild:
    def test_published_included(self):
        assert len(filter_for_build([_post()])) == 1

    def test_draft_excluded(self):
        assert len(filter_for_build([_post(published=False)])) == 0

    def test_draft_overrides_encrypted(self):
        assert len(filter_for_build([_post(published=False, encrypted=True)])) == 0

    def test_unlisted_included_in_build(self):
        assert len(filter_for_build([_post(unlisted=True)])) == 1

    def test_encrypted_included_in_build(self):
        assert len(filter_for_build([_post(encrypted=True)])) == 1

class TestFilterForIndex:
    def test_unlisted_excluded(self):
        assert len(filter_for_index([_post(unlisted=True)])) == 0

    def test_encrypted_included(self):
        result = filter_for_index([_post(encrypted=True)])
        assert len(result) == 1

class TestFilterForFeed:
    def test_unlisted_excluded(self):
        assert len(filter_for_feed([_post(unlisted=True)])) == 0

class TestFilterForSitemap:
    def test_unlisted_excluded(self):
        assert len(filter_for_sitemap([_post(unlisted=True)])) == 0

    def test_encrypted_excluded(self):
        assert len(filter_for_sitemap([_post(encrypted=True)])) == 0

class TestFilterForSearch:
    def test_encrypted_excluded(self):
        assert len(filter_for_search([_post(encrypted=True)])) == 0

    def test_unlisted_excluded(self):
        assert len(filter_for_search([_post(unlisted=True)])) == 0


class TestFilterForServeBuild:
    def test_draft_included(self):
        assert len(filter_for_serve_build([_post(published=False)])) == 1

    def test_published_included(self):
        assert len(filter_for_serve_build([_post()])) == 1

    def test_unlisted_included(self):
        assert len(filter_for_serve_build([_post(unlisted=True)])) == 1


class TestFilterForServeIndex:
    def test_draft_included(self):
        assert len(filter_for_serve_index([_post(published=False)])) == 1

    def test_unlisted_excluded(self):
        assert len(filter_for_serve_index([_post(unlisted=True)])) == 0
