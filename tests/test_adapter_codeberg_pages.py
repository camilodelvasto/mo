"""Tests for Codeberg Pages deploy adapter."""
import pytest
from shapes.shared.adapters.codeberg_pages import (
    _validate_config,
    _derive_url,
    _extra_root_files,
    _custom_domain,
    _validate_custom_domain,
    CodebergError,
)


def _valid_config(**overrides):
    base = {
        "repo_url": "https://codeberg.org/user/repo.git",
        "branch": "pages",
        "git_user": "user",
        "git_email": "u@e.com",
    }
    base.update(overrides)
    return base


class TestValidateConfig:
    def test_valid_config(self):
        _validate_config(_valid_config())

    def test_missing_repo_url_throws(self):
        with pytest.raises(CodebergError, match="repo_url"):
            _validate_config({"branch": "pages", "git_user": "u", "git_email": "e"})

    def test_missing_branch_throws(self):
        with pytest.raises(CodebergError, match="branch"):
            _validate_config({"repo_url": "x", "git_user": "u", "git_email": "e"})

    def test_missing_git_user_throws(self):
        with pytest.raises(CodebergError, match="git_user"):
            _validate_config({"repo_url": "x", "branch": "pages", "git_email": "e"})

    def test_missing_git_email_throws(self):
        with pytest.raises(CodebergError, match="git_email"):
            _validate_config({"repo_url": "x", "branch": "pages", "git_user": "u"})

    def test_empty_repo_url_throws(self):
        with pytest.raises(CodebergError, match="repo_url"):
            _validate_config(_valid_config(repo_url=""))


class TestCustomDomain:
    def test_custom_domain_detected(self):
        config = _valid_config(domain="www.moui.io")
        assert _custom_domain(config) == "www.moui.io"

    def test_no_custom_domain_for_codeberg_page(self):
        config = _valid_config(domain="moui.codeberg.page")
        assert _custom_domain(config) is None

    def test_no_custom_domain_when_missing(self):
        config = _valid_config()
        assert _custom_domain(config) is None


class TestValidateCustomDomain:
    def test_raises_when_aliases_and_non_root_publish_path(self):
        config = _valid_config(domain="www.moui.io", aliases=["moui.io"])
        with pytest.raises(CodebergError, match="aliases"):
            _validate_custom_domain(config, "/grove")

    def test_succeeds_with_custom_domain_and_root_publish_path(self):
        config = _valid_config(domain="www.moui.io")
        _validate_custom_domain(config, "/")  # no exception

    def test_succeeds_with_custom_domain_and_non_root_publish_path(self):
        config = _valid_config(domain="www.moui.io")
        _validate_custom_domain(config, "/decks/pitch")  # subdirectory deploy is valid

    def test_succeeds_with_default_domain_and_non_root_publish_path(self):
        config = _valid_config(domain="moui.codeberg.page")
        _validate_custom_domain(config, "/grove")  # no exception

    def test_succeeds_when_no_domain(self):
        config = _valid_config()
        _validate_custom_domain(config, "/grove")  # no exception


class TestExtraRootFiles:
    def test_domains_file_written_for_custom_domain(self):
        config = _valid_config(domain="www.moui.io")
        files = _extra_root_files(config)
        assert files[".domains"] == "www.moui.io\n"

    def test_domains_file_with_aliases(self):
        config = _valid_config(domain="www.moui.io", aliases=["moui.io"])
        files = _extra_root_files(config)
        assert files[".domains"] == "www.moui.io\nmoui.io\n"

    def test_no_domains_file_for_default_domain(self):
        config = _valid_config(domain="moui.codeberg.page")
        files = _extra_root_files(config)
        assert ".domains" not in files

    def test_no_domains_file_when_no_domain(self):
        config = _valid_config()
        files = _extra_root_files(config)
        assert ".domains" not in files


class TestDeriveUrl:
    def test_derive_from_https_repo_url(self):
        config = _valid_config(repo_url="https://codeberg.org/moui/pages.git")
        assert _derive_url(config, "/grove") == "https://moui.codeberg.page/grove"

    def test_derive_from_ssh_repo_url(self):
        config = _valid_config(repo_url="git@codeberg.org:moui/pages.git")
        assert _derive_url(config, "/grove") == "https://moui.codeberg.page/grove"

    def test_custom_domain_overrides_derivation(self):
        config = _valid_config(domain="my.domain.com")
        assert _derive_url(config, "/") == "https://my.domain.com/"

    def test_non_codeberg_url_throws(self):
        config = _valid_config(repo_url="https://example.com/x/y.git")
        with pytest.raises(CodebergError, match="Cannot derive"):
            _derive_url(config, "/grove")


def test_deploy_returns_live(monkeypatch, tmp_path):
    import contextlib
    from shapes.shared.adapters import codeberg_pages as adapter
    from shapes.shared.adapters.outcome import Live
    pushed = []

    @contextlib.contextmanager
    def clone_and_merge(*a, **k):
        yield tmp_path
    monkeypatch.setattr(adapter, "clone_and_merge", clone_and_merge)
    monkeypatch.setattr(adapter, "push", lambda *a, **k: pushed.append(a))
    out = adapter.deploy(tmp_path, _valid_config(), "/grove")
    assert pushed and isinstance(out, Live) and out.url.endswith("/grove")
