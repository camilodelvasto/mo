"""Tests for the new mo deploy command."""
from pathlib import Path

import pytest
import yaml


def _setup_corpus(tmp_path):
    """Create minimal corpus with infrastructure, content, and moui.json."""
    (tmp_path / "moui.json").write_text("{}")

    # Content
    content = tmp_path / "content" / "moui" / "website" / "en"
    content.mkdir(parents=True)

    # Infrastructure
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "remotes.yaml").write_text(yaml.dump({
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
    }))

    targets = infra / "targets" / "moui" / "website"
    targets.mkdir(parents=True)
    (targets / "en.yaml").write_text(yaml.dump({
        "content": "moui/website/en",
        "shape": "grove",
        "environments": {
            "prod": {
                "domain": "moui.io",
                "base_path": "/",
                "encrypted": False,
                "remote": "codeberg/moui-pages",
                "publish_path": "/",
            }
        }
    }))

    return tmp_path


def test_resolve_deploy(tmp_path):
    from cli.commands.deploy import _resolve_deploy

    corpus = _setup_corpus(tmp_path)
    content_path = corpus / "content" / "moui" / "website" / "en"

    target, env, remote, base_url = _resolve_deploy(corpus, content_path, "prod")
    assert target["shape"] == "grove"
    assert env["remote"] == "codeberg/moui-pages"
    assert base_url == "https://moui.io/"
    assert remote["adapter"] == "codeberg_pages"


def test_resolve_deploy_raises_on_unknown_env(tmp_path):
    from cli.commands.deploy import _resolve_deploy
    from cli.infra.targets import TargetError

    corpus = _setup_corpus(tmp_path)
    content_path = corpus / "content" / "moui" / "website" / "en"

    with pytest.raises(TargetError, match="staging"):
        _resolve_deploy(corpus, content_path, "staging")


def test_build_config_merges_remote_and_credentials():
    from cli.commands.deploy import _build_config_for_adapter

    remote = {
        "adapter": "codeberg_pages",
        "repo": "git@codeberg.org:moui/pages.git",
        "branch": "pages",
        "git_user": "bot",
        "git_email": "bot@x",
        "credential": "ssh-agent",
    }
    credentials = {"token": "ghp_xxx"}
    env = {"domain": "moui.io", "base_path": "/", "publish_path": "/", "remote": "codeberg/moui-pages"}

    config = _build_config_for_adapter(remote, credentials, env)
    assert config["repo_url"] == "git@codeberg.org:moui/pages.git"
    assert config["branch"] == "pages"
    assert config["git_user"] == "bot"
    assert config["token"] == "ghp_xxx"
    assert config["domain"] == "moui.io"
    assert "adapter" not in config  # adapter is not a config field
    assert "credential" not in config  # credential is not a config field


def test_build_config_handles_s3_remote():
    from cli.commands.deploy import _build_config_for_adapter

    remote = {
        "adapter": "s3",
        "bucket": "my-bucket",
        "region": "us-east-1",
        "endpoint": "https://s3.example.com",
        "credential": {"type": "env", "var": "AWS_TOKEN"},
    }
    credentials = {"token": "aws_xxx"}
    env = {"domain": "cdn.example.com", "base_path": "/", "publish_path": "/", "remote": "s3/bucket"}

    config = _build_config_for_adapter(remote, credentials, env)
    assert config["bucket"] == "my-bucket"
    assert config["region"] == "us-east-1"
    assert config["endpoint"] == "https://s3.example.com"
    assert config["token"] == "aws_xxx"
    assert config["domain"] == "cdn.example.com"
    assert "adapter" not in config
    assert "credential" not in config


def test_build_config_handles_hetzner_remote():
    from cli.commands.deploy import _build_config_for_adapter

    remote = {
        "adapter": "hetzner",
        "host": "deploy.example.com",
        "user": "deployer",
        "path": "/var/www/site",
        "credential": "ssh-agent",
    }
    credentials = {}
    env = {"domain": "example.com", "base_path": "/", "publish_path": "/", "remote": "hetzner/site"}

    config = _build_config_for_adapter(remote, credentials, env)
    assert config["host"] == "deploy.example.com"
    assert config["user"] == "deployer"
    assert config["path"] == "/var/www/site"
    assert config["domain"] == "example.com"
    assert "adapter" not in config


def test_run_dry_run(tmp_path, capsys, monkeypatch):
    """--dry-run should resolve and print but not build or deploy."""
    from cli.commands import deploy
    from cli.commands.deploy import run

    real = deploy._load_adapter               # tmp corpus has no shapes/: use the repo's adapters
    monkeypatch.setattr(deploy, "_load_adapter",
                        lambda cr, name: real(Path(__file__).resolve().parents[1], name))
    corpus = _setup_corpus(tmp_path)
    content_path = str(corpus / "content" / "moui" / "website" / "en")

    run(corpus, None, [content_path, "prod", "--dry-run"])

    captured = capsys.readouterr()
    assert "dry-run" in captured.out.lower()
    assert "moui.io" in captured.out


def test_run_missing_args(tmp_path):
    """run() with fewer than 2 positional args should exit."""
    from cli.commands.deploy import run

    corpus = _setup_corpus(tmp_path)

    with pytest.raises(SystemExit):
        run(corpus, None, ["some-path"])


def test_stack_target_dispatches_to_stack_rail(tmp_path, monkeypatch):
    from cli.commands import deploy
    (tmp_path / "moui.json").write_text("{}")
    infra = tmp_path / "infrastructure"; infra.mkdir()
    (infra / "remotes.yaml").write_text(
        "remotes:\n  hetzner/x:\n    host: h\n    user: u\n    path: /opt/cs\n")
    tdir = infra / "targets" / "corpus-server"; tdir.mkdir(parents=True)
    (tdir / "acme.yaml").write_text(
        "stack: corpus-server\nconverge: compose\nenvironments:\n  prod:\n"
        "    remote: hetzner/x\n    corpus: cx\n    content: content/x\n"
        "    domain: ask.moui.co\n    grove_origins: [https://ask.moui.co]\n"
        "    exposed_asks: [answer]\n    auth: { scheme: none }\n"
        "    roles: { standard: { cap: 5 } }\n    default_role: standard\n"
        "    window: month\n"
        "    rate_limit: { per_minute: 60, block_after: 10, block_for: 15m }\n")
    seen = {}
    monkeypatch.setattr("cli.deploy.stack.run",
                        lambda root, t, e, r, en: seen.update(stack=t["stack"], env=en))
    deploy.run(tmp_path, None, ["corpus-server/acme", "prod"])
    assert seen == {"stack": "corpus-server", "env": "prod"}


def test_both_shape_and_stack_fails_loud(tmp_path):
    import pytest
    from cli.commands import deploy
    (tmp_path / "moui.json").write_text("{}")
    infra = tmp_path / "infrastructure"; infra.mkdir()
    (infra / "remotes.yaml").write_text("remotes:\n  r/x:\n    host: h\n    user: u\n    path: /p\n")
    tdir = infra / "targets" / "bad"; tdir.mkdir(parents=True)
    (tdir / "t.yaml").write_text(
        "shape: grove\nstack: corpus-server\nenvironments:\n  prod:\n    remote: r/x\n")
    with pytest.raises(SystemExit, match="exactly one of"):
        deploy.run(tmp_path, None, ["bad/t", "prod"])
