"""Tests for infrastructure/remotes.yaml loading and validation."""
from pathlib import Path

import pytest
import yaml


def _write_remotes(tmp_path, remotes_dict):
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "remotes.yaml").write_text(yaml.dump(remotes_dict, default_flow_style=False))
    return tmp_path


def test_load_remotes_returns_dict(tmp_path):
    from cli.infra.remotes import load_remotes

    _write_remotes(tmp_path, {
        "remotes": {
            "codeberg/moui-pages": {
                "adapter": "codeberg_pages",
                "repo": "git@codeberg.org:moui/pages.git",
                "branch": "pages",
                "git_user": "moui-bot",
                "git_email": "deploy@moui.io",
                "credential": "ssh-agent",
            }
        }
    })
    result = load_remotes(tmp_path)
    assert "codeberg/moui-pages" in result
    assert result["codeberg/moui-pages"]["adapter"] == "codeberg_pages"


def test_load_remotes_raises_when_file_missing(tmp_path):
    from cli.infra.remotes import load_remotes, RemotesError

    with pytest.raises(RemotesError, match="remotes.yaml"):
        load_remotes(tmp_path)


def test_load_remotes_raises_on_empty_remotes(tmp_path):
    from cli.infra.remotes import load_remotes, RemotesError

    _write_remotes(tmp_path, {"remotes": {}})
    with pytest.raises(RemotesError, match="no remotes defined"):
        load_remotes(tmp_path)


def test_get_remote_raises_on_unknown(tmp_path):
    from cli.infra.remotes import load_remotes, get_remote, RemotesError

    _write_remotes(tmp_path, {
        "remotes": {
            "codeberg/moui-pages": {
                "adapter": "codeberg_pages",
                "repo": "git@codeberg.org:moui/pages.git",
                "branch": "pages",
                "git_user": "bot",
                "git_email": "bot@x",
                "credential": "ssh-agent",
            }
        }
    })
    remotes = load_remotes(tmp_path)
    with pytest.raises(RemotesError, match=r"(?s)codeberg/typo.*Known remotes:"):
        get_remote(remotes, "codeberg/typo")


def test_get_remote_returns_match(tmp_path):
    from cli.infra.remotes import load_remotes, get_remote

    _write_remotes(tmp_path, {
        "remotes": {
            "codeberg/moui-pages": {
                "adapter": "codeberg_pages",
                "repo": "git@codeberg.org:moui/pages.git",
                "branch": "pages",
                "git_user": "bot",
                "git_email": "bot@x",
                "credential": "ssh-agent",
            }
        }
    })
    remotes = load_remotes(tmp_path)
    remote = get_remote(remotes, "codeberg/moui-pages")
    assert remote["adapter"] == "codeberg_pages"
