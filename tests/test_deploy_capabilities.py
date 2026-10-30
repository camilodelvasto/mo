# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import types
import pytest
from cli.commands.deploy import _adapter_capabilities


def _root(tmp_path):
    (tmp_path / "infrastructure/targets").mkdir(parents=True)
    (tmp_path / "infrastructure/dns.yaml").write_text(
        "zones:\n  moui.io: {provider: route53, aws_profile: default}\n")
    return tmp_path


def test_injects_what_the_adapter_requires(tmp_path):
    mod = types.SimpleNamespace(__name__="a", REQUIRES=("dns", "declared_mounts", "remote_id"))
    caps = _adapter_capabilities(_root(tmp_path), mod, {"domain": "www.moui.io"},
                                 "hetzner/web", take_dns=True)
    assert set(caps) == {"dns", "declared_mounts", "remote_id"}
    assert caps["declared_mounts"] == {}
    assert caps["remote_id"] == "hetzner/web"
    assert caps["dns"].refused([]) == []


def test_declared_mounts_spans_every_remote_for_the_domain(tmp_path):
    root = _root(tmp_path)
    (root / "infrastructure/targets/en.yaml").write_text(
        "shape: grove\nenvironments:\n"
        "  prod: {remote: github/g, domain: www.moui.io, publish_path: /}\n"
        "  next: {remote: hetzner/web, domain: www.moui.io, publish_path: /es}\n")
    mod = types.SimpleNamespace(__name__="a", REQUIRES=("declared_mounts",))
    caps = _adapter_capabilities(root, mod, {"domain": "www.moui.io"}, "hetzner/web",
                                 take_dns=False)
    assert caps["declared_mounts"] == {"/": [("github/g", "infrastructure/targets/en.yaml")],
                                       "/es": [("hetzner/web", "infrastructure/targets/en.yaml")]}


def test_adapter_without_requires_fails_loud(tmp_path):
    with pytest.raises(SystemExit, match="REQUIRES"):
        _adapter_capabilities(tmp_path, types.SimpleNamespace(__name__="a"), {}, "r", take_dns=False)


def test_unknown_capability_fails_loud(tmp_path):
    mod = types.SimpleNamespace(__name__="a", REQUIRES=("teleport",))
    with pytest.raises(SystemExit, match="teleport"):
        _adapter_capabilities(tmp_path, mod, {}, "r", take_dns=False)


def test_take_dns_on_an_adapter_without_dns_fails_loud(tmp_path):
    mod = types.SimpleNamespace(__name__="github_pages", REQUIRES=())
    with pytest.raises(SystemExit, match="--take-dns"):
        _adapter_capabilities(tmp_path, mod, {}, "github/g", take_dns=True)


def test_every_deploy_adapter_declares_requires():
    from pathlib import Path
    import importlib
    adapters = Path(__file__).resolve().parents[1] / "shapes/shared/adapters"
    files = sorted(adapters.glob("*.py"))
    assert files, f"no adapters found under {adapters}"
    for f in files:
        if f.stem in ("git_sync", "outcome", "__init__"):
            continue                       # git_sync is a sync transport; outcome is the return contract
        mod = importlib.import_module(f"shapes.shared.adapters.{f.stem}")
        assert hasattr(mod, "REQUIRES"), f.stem


@pytest.mark.parametrize("requires", [["dns"], "dns", ("dns", 3), None])
def test_requires_not_a_tuple_of_str_fails_loud(tmp_path, requires):
    mod = types.SimpleNamespace(__name__="badapter", REQUIRES=requires)
    with pytest.raises(SystemExit, match="badapter.*tuple of str"):
        _adapter_capabilities(tmp_path, mod, {}, "r", take_dns=False)


def test_check_capabilities_is_the_validation_alone():
    from cli.commands.deploy import _check_capabilities
    _check_capabilities(types.SimpleNamespace(__name__="h", REQUIRES=("dns",)), "r", take_dns=True)
    with pytest.raises(SystemExit, match="--take-dns"):
        _check_capabilities(types.SimpleNamespace(__name__="g", REQUIRES=()), "r", take_dns=True)
