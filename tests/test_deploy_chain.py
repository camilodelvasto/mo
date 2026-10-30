# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from pathlib import Path
from cli.commands import deploy

REPO = Path(__file__).resolve().parents[1]


def _infra(tmp_path):
    (tmp_path / "moui.json").write_text("{}")
    infra = tmp_path / "infrastructure"; (infra / "targets" / "clients" / "p").mkdir(parents=True)
    (infra / "remotes.yaml").write_text(
        "remotes:\n  hetzner/x:\n    host: h\n    user: u\n    path: /opt/cs\n"
        "  gh/p:\n    adapter: github_pages\n    repo: g\n    branch: b\n    git_user: u\n"
        "    git_email: e\n    credential: ssh-agent\n")
    # the box stack (provider)
    (infra / "targets" / "clients" / "p" / "corpus.yaml").write_text(
        "stack: corpus-server\nconverge: compose\nenvironments:\n  prod:\n    remote: hetzner/x\n"
        "    corpus: cx\n    content: content/clients/p/corpus\n")
    # the grove (self), declaring the ask dependency
    (infra / "targets" / "clients" / "p" / "site.yaml").write_text(
        "shape: grove\nenvironments:\n  prod:\n    remote: gh/p\n    domain: d\n    base_path: /\n"
        "    publish_path: /p\n    crawlable: full\n    services:\n"
        "      chat: clients/p/corpus\n")
    return tmp_path


@pytest.fixture(autouse=True)
def _real_adapters(monkeypatch):
    """The tmp corpus has no shapes/; load the repo's real adapters."""
    real = deploy._load_adapter
    monkeypatch.setattr(deploy, "_load_adapter", lambda cr, name: real(REPO, name))


def test_chain_deploys_provider_then_self_then_syncs(tmp_path, monkeypatch):
    root = _infra(tmp_path)
    order = []
    monkeypatch.setattr(deploy, "_deploy_one",
        lambda cr, ref, env, force, dry, **kw: order.append(("deploy", str(ref))))
    monkeypatch.setattr("cli.sync.corpus.sync.run",
        lambda cr, ref, env, *, now: order.append(("sync", ref)))
    deploy.run(root, None, ["clients/p/site", "prod"])
    assert order == [("deploy", "clients/p/corpus"),   # provider first
                     ("deploy", "clients/p/site"),      # self
                     ("sync", "clients/p/corpus")]      # corpus last


def test_no_services_deploys_only_self(tmp_path, monkeypatch):
    root = _infra(tmp_path)
    (root / "infrastructure/targets/clients/p/site.yaml").write_text(
        "shape: grove\nenvironments:\n  prod:\n    remote: gh/p\n    domain: d\n    base_path: /\n"
        "    publish_path: /p\n    crawlable: full\n")    # no services
    calls = []
    monkeypatch.setattr(deploy, "_deploy_one", lambda cr, ref, e, f, d, **kw: calls.append(str(ref)))
    monkeypatch.setattr("cli.sync.corpus.sync.run", lambda *a, **k: calls.append("SYNC"))
    deploy.run(root, None, ["clients/p/site", "prod"])
    assert calls == ["clients/p/site"] and "SYNC" not in calls


def test_no_chain_flag_deploys_only_self(tmp_path, monkeypatch):
    root = _infra(tmp_path)
    calls = []
    monkeypatch.setattr(deploy, "_deploy_one", lambda cr, ref, e, f, d, **kw: calls.append(str(ref)))
    monkeypatch.setattr("cli.sync.corpus.sync.run", lambda *a, **k: calls.append("SYNC"))
    deploy.run(root, None, ["clients/p/site", "prod", "--no-chain"])
    assert calls == ["clients/p/site"] and "SYNC" not in calls


def test_take_dns_reaches_self_only(tmp_path, monkeypatch):
    root = _infra(tmp_path)
    (root / "infrastructure/remotes.yaml").write_text(
        (root / "infrastructure/remotes.yaml").read_text() +
        "  hetzner/web:\n    adapter: hetzner\n    host: h\n    user: u\n    path: /opt/cs\n"
        "    credential: ssh-agent\n")
    site = root / "infrastructure/targets/clients/p/site.yaml"
    site.write_text(site.read_text().replace("remote: gh/p", "remote: hetzner/web"))
    seen = {}
    monkeypatch.setattr(deploy, "_deploy_one",
        lambda cr, ref, e, f, d, **kw: seen.__setitem__(str(ref), kw))
    monkeypatch.setattr("cli.sync.corpus.sync.run", lambda *a, **k: None)
    deploy.run(root, None, ["clients/p/site", "prod", "--take-dns"])
    assert seen == {"clients/p/corpus": {"take_dns": False},
                    "clients/p/site": {"take_dns": True}}


def test_dry_run_take_dns_on_dns_grove_reports_it(tmp_path, capsys):
    root = _infra(tmp_path)
    (root / "infrastructure/dns.yaml").write_text(
        "zones:\n  moui.io: {provider: route53, aws_profile: default}\n")
    (root / "infrastructure/remotes.yaml").write_text(
        (root / "infrastructure/remotes.yaml").read_text() +
        "  hetzner/web:\n    adapter: hetzner\n    host: h\n    user: u\n    path: /opt/cs\n"
        "    credential: ssh-agent\n")
    site = root / "infrastructure/targets/clients/p/site.yaml"
    site.write_text(site.read_text().replace("remote: gh/p", "remote: hetzner/web")
                    .replace("domain: d", "domain: www.moui.io"))
    deploy.run(root, None, ["clients/p/site", "prod", "--no-chain", "--dry-run", "--take-dns"])
    out = capsys.readouterr().out
    assert "take-dns:" in out and "yes" in out


def test_take_dns_on_non_dns_grove_refuses_before_any_provider(tmp_path, monkeypatch):
    root = _infra(tmp_path)                 # self is a github_pages grove
    calls = []
    monkeypatch.setattr(deploy, "_deploy_one", lambda *a, **kw: calls.append(a[1]))
    monkeypatch.setattr("cli.sync.corpus.sync.run", lambda *a, **k: calls.append("SYNC"))
    with pytest.raises(SystemExit, match="--take-dns"):
        deploy.run(root, None, ["clients/p/site", "prod", "--take-dns"])
    assert calls == []


@pytest.mark.parametrize("extra", [[], ["--dry-run"]])
def test_take_dns_on_stack_refuses(tmp_path, monkeypatch, extra):
    root = _infra(tmp_path)
    calls = []
    monkeypatch.setattr("cli.deploy.stack.run", lambda *a, **k: calls.append("STACK"))
    with pytest.raises(SystemExit, match="--take-dns"):
        deploy.run(root, None, ["clients/p/corpus", "prod", "--take-dns", *extra])
    assert calls == []


def test_dry_run_take_dns_on_non_dns_grove_refuses(tmp_path):
    root = _infra(tmp_path)
    with pytest.raises(SystemExit, match="--take-dns"):
        deploy.run(root, None, ["clients/p/site", "prod", "--no-chain", "--dry-run", "--take-dns"])


def test_deploy_one_dry_run_take_dns_on_stack_refuses(tmp_path):
    root = _infra(tmp_path)
    with pytest.raises(SystemExit, match="--take-dns"):
        deploy._deploy_one(root, "clients/p/corpus", "prod", False, True, take_dns=True)


def test_deploy_one_dry_run_take_dns_on_non_dns_grove_refuses(tmp_path):
    root = _infra(tmp_path)
    with pytest.raises(SystemExit, match="--take-dns"):
        deploy._deploy_one(root, "clients/p/site", "prod", False, True, take_dns=True)


def test_unknown_flag_refuses(tmp_path):
    root = _infra(tmp_path)
    with pytest.raises(SystemExit, match=r"unknown flag --tke-dns \(known: --force --dry-run --no-chain --take-dns\)"):
        deploy.run(root, None, ["clients/p/site", "prod", "--tke-dns"])


def test_provider_env_aliasing_another_env_is_named(tmp_path, monkeypatch, capsys):
    root = _infra(tmp_path)
    (root / "infrastructure/targets/clients/p/corpus.yaml").write_text(
        "stack: corpus-server\nconverge: compose\nenvironments:\n  prod: &prod\n"
        "    remote: hetzner/x\n    domain: ask.moui.co\n    corpus: cx\n"
        "    content: content/clients/p/corpus\n  hetzner-staging: *prod\n")
    site = root / "infrastructure/targets/clients/p/site.yaml"
    site.write_text(site.read_text().replace("  prod:\n", "  hetzner-staging:\n"))
    monkeypatch.setattr(deploy, "_deploy_one", lambda *a, **kw: None)
    monkeypatch.setattr("cli.sync.corpus.sync.run", lambda *a, **k: None)
    deploy.run(root, None, ["clients/p/site", "hetzner-staging"])
    assert ("clients/p/corpus hetzner-staging is the same box config as prod (ask.moui.co) "
            "— this deploys and syncs it") in capsys.readouterr().out


def test_provider_env_with_its_own_config_prints_no_alias_note(tmp_path, monkeypatch, capsys):
    root = _infra(tmp_path)
    monkeypatch.setattr(deploy, "_deploy_one", lambda *a, **kw: None)
    monkeypatch.setattr("cli.sync.corpus.sync.run", lambda *a, **k: None)
    deploy.run(root, None, ["clients/p/site", "prod"])
    assert "same box config" not in capsys.readouterr().out
