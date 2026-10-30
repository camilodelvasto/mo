"""Tests for GitHub Pages deploy adapter."""
import pytest
from shapes.shared.adapters.github_pages import (
    _validate_config,
    _derive_url,
    _extra_root_files,
    _custom_domain,
    _validate_custom_domain,
    GitHubPagesError,
)


def _valid_config(**overrides):
    base = {
        "repo_url": "https://github.com/user/repo.git",
        "branch": "gh-pages",
        "git_user": "user",
        "git_email": "u@e.com",
    }
    base.update(overrides)
    return base


class TestValidateConfig:
    def test_valid_config(self):
        _validate_config(_valid_config())

    def test_missing_repo_url_throws(self):
        with pytest.raises(GitHubPagesError, match="repo_url"):
            _validate_config({"branch": "gh-pages", "git_user": "u", "git_email": "e"})

    def test_missing_branch_throws(self):
        with pytest.raises(GitHubPagesError, match="branch"):
            _validate_config({"repo_url": "x", "git_user": "u", "git_email": "e"})

    def test_missing_git_user_throws(self):
        with pytest.raises(GitHubPagesError, match="git_user"):
            _validate_config({"repo_url": "x", "branch": "gh-pages", "git_email": "e"})

    def test_missing_git_email_throws(self):
        with pytest.raises(GitHubPagesError, match="git_email"):
            _validate_config({"repo_url": "x", "branch": "gh-pages", "git_user": "u"})

    def test_empty_repo_url_throws(self):
        with pytest.raises(GitHubPagesError, match="repo_url"):
            _validate_config(_valid_config(repo_url=""))


class TestCustomDomain:
    def test_custom_domain_detected(self):
        config = _valid_config(domain="www.example.com")
        assert _custom_domain(config) == "www.example.com"

    def test_no_custom_domain_for_github_io(self):
        config = _valid_config(domain="user.github.io")
        assert _custom_domain(config) is None

    def test_no_custom_domain_when_missing(self):
        config = _valid_config()
        assert _custom_domain(config) is None


class TestValidateCustomDomain:
    def test_raises_when_aliases_and_non_root_publish_path(self):
        config = _valid_config(domain="www.example.com", aliases=["example.com"])
        with pytest.raises(GitHubPagesError, match="aliases"):
            _validate_custom_domain(config, "/grove")

    def test_succeeds_with_custom_domain_and_root_publish_path(self):
        config = _valid_config(domain="www.example.com")
        _validate_custom_domain(config, "/")  # no exception

    def test_succeeds_with_custom_domain_and_non_root_publish_path(self):
        config = _valid_config(domain="www.example.com")
        _validate_custom_domain(config, "/decks/pitch")  # subdirectory deploy is valid

    def test_succeeds_with_default_domain_and_non_root_publish_path(self):
        config = _valid_config(domain="user.github.io")
        _validate_custom_domain(config, "/grove")  # no exception

    def test_succeeds_when_no_domain(self):
        config = _valid_config()
        _validate_custom_domain(config, "/grove")  # no exception


class TestDeriveUrl:
    def test_derive_from_https_repo_url(self):
        config = _valid_config(repo_url="https://github.com/user/repo.git")
        assert _derive_url(config, "/grove") == "https://user.github.io/repo/grove"

    def test_derive_from_ssh_repo_url(self):
        config = _valid_config(repo_url="git@github.com:user/repo.git")
        assert _derive_url(config, "/grove") == "https://user.github.io/repo/grove"

    def test_custom_domain_overrides_derivation(self):
        config = _valid_config(domain="my.domain.com")
        assert _derive_url(config, "/") == "https://my.domain.com/"

    def test_non_github_url_throws(self):
        config = _valid_config(repo_url="https://example.com/x/y.git")
        with pytest.raises(GitHubPagesError, match="Cannot derive"):
            _derive_url(config, "/grove")


class TestExtraRootFiles:
    def test_always_includes_nojekyll(self):
        files = _extra_root_files(_valid_config())
        assert ".nojekyll" in files

    def test_cname_written_for_custom_domain(self):
        files = _extra_root_files(_valid_config(domain="my.domain.com"))
        assert files["CNAME"] == "my.domain.com\n"

    def test_no_cname_for_default_domain(self):
        files = _extra_root_files(_valid_config(domain="user.github.io"))
        assert "CNAME" not in files

    def test_no_cname_when_no_domain(self):
        files = _extra_root_files(_valid_config())
        assert "CNAME" not in files


def test_deploy_returns_live(monkeypatch, tmp_path):
    import contextlib
    from shapes.shared.adapters import github_pages as adapter
    from shapes.shared.adapters.outcome import Live
    pushed = []

    @contextlib.contextmanager
    def clone_and_merge(*a, **k):
        yield tmp_path
    monkeypatch.setattr(adapter, "clone_and_merge", clone_and_merge)
    monkeypatch.setattr(adapter, "push", lambda *a, **k: pushed.append(a))
    out = adapter.deploy(tmp_path, _valid_config(), "/grove")
    assert pushed and isinstance(out, Live) and out.url.endswith("/grove")
