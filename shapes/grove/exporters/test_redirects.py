"""Tests for grove redirects generator."""
from redirects import generate_redirects_file, generate_caddy_redirects

def _post(url_path="/new-path/", redirects=None):
    return {"url_path": url_path, "redirects": redirects or [], "title": "T"}

class TestGenerateRedirectsFile:
    def test_generates_netlify_format(self):
        posts = [_post(url_path="/new/", redirects=["old-path", "another/old"])]
        output = generate_redirects_file(posts)
        assert "/old-path/ /new/ 301" in output
        assert "/another/old/ /new/ 301" in output

    def test_no_redirects_empty(self):
        posts = [_post()]
        output = generate_redirects_file(posts)
        assert output.strip() == ""

class TestGenerateCaddyRedirects:
    def test_generates_caddy_format(self):
        posts = [_post(url_path="/new/", redirects=["old-path"])]
        output = generate_caddy_redirects(posts)
        assert "redir /old-path/ /new/ 301" in output
