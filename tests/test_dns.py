# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import importlib

import pytest
from cli.infra.dns import Action, Dns, DnsError, decide, load_zones, resolve_provider, zone_for

BOX = "203.0.113.7"


def test_decide_create_keep_replace():
    assert decide([], BOX) == "create"
    assert decide([{"type": "A", "values": [BOX]}], BOX) == "keep"
    assert decide([{"type": "CNAME", "values": ["x.github.io"]}], BOX) == "replace"
    assert decide([{"type": "A", "values": ["185.199.108.153"]}], BOX) == "replace"
    # an A at the box plus anything else is not "ours"
    assert decide([{"type": "A", "values": [BOX]},
                   {"type": "AAAA", "values": ["::1"]}], BOX) == "replace"


def test_zone_for_longest_suffix_and_undeclared_throws():
    zones = {"moui.io": {}, "moui.co": {}, "x.moui.co": {}}
    assert zone_for("www.moui.io", zones) == "moui.io"
    assert zone_for("moui.io", zones) == "moui.io"
    assert zone_for("a.x.moui.co", zones) == "x.moui.co"
    with pytest.raises(DnsError, match="evilmoui.io.*no zone"):
        zone_for("evilmoui.io", zones)


def test_load_zones_requires_file_and_provider(tmp_path):
    with pytest.raises(DnsError, match="dns.yaml"):
        load_zones(tmp_path)
    (tmp_path / "infrastructure").mkdir()
    (tmp_path / "infrastructure/dns.yaml").write_text("zones:\n  moui.io: {aws_profile: d}\n")
    with pytest.raises(DnsError, match="moui.io declares no provider"):
        load_zones(tmp_path)


@pytest.mark.parametrize("body, msg", [
    ("", "top level must be a mapping"),
    ("- zones\n", "top level must be a mapping"),
    ("zones: [moui.io]\n", "zones must be a mapping"),
    ("other: 1\n", "no zones declared"),
])
def test_load_zones_rejects_non_mapping_shapes(tmp_path, body, msg):
    (tmp_path / "infrastructure").mkdir()
    (tmp_path / "infrastructure/dns.yaml").write_text(body)
    with pytest.raises(DnsError, match=msg):
        load_zones(tmp_path)


def test_resolve_provider_unknown_is_named():
    with pytest.raises(DnsError, match="unknown dns provider 'nope'"):
        resolve_provider("nope")


def test_resolve_provider_reraises_a_missing_dependency(monkeypatch):
    # A provider that exists but cannot import its own dependency is not "unknown".
    def boom(name):
        raise ModuleNotFoundError("No module named 'boto3'", name="boto3")
    monkeypatch.setattr(importlib, "import_module", boom)
    with pytest.raises(ModuleNotFoundError, match="boto3"):
        resolve_provider("route53")


class FakeProvider:
    def __init__(self, table): self.table, self.applied = table, []
    def records(self, zone, name, spec): return self.table.get(name, [])
    def apply(self, zone, changes, address, spec):
        self.applied.append((zone, [n for n, _ in changes], address))


def _dns(table, take, zones=None):
    prov = FakeProvider(table)
    zones = zones or {"moui.io": {"provider": "fake"}}
    return Dns(zones, take=take, resolve=lambda name: prov), prov


def test_plan_then_apply_skips_keep():
    dns, prov = _dns({"www.moui.io": [{"type": "A", "values": [BOX]}]}, take=False)
    actions = dns.plan(["www.moui.io", "next.moui.io"], BOX)
    assert [(a.name, a.kind, a.address) for a in actions] == [
        ("www.moui.io", "keep", BOX), ("next.moui.io", "create", BOX)]
    assert dns.refused(actions) == []
    dns.apply(actions)
    assert prov.applied == [("moui.io", ["next.moui.io"], BOX)]


def test_replace_refused_without_take_and_nothing_applied():
    dns, prov = _dns({"www.moui.io": [{"type": "CNAME", "values": ["c.github.io"]}]}, take=False)
    actions = dns.plan(["next.moui.io", "www.moui.io"], BOX)
    assert [a.name for a in dns.refused(actions)] == ["www.moui.io"]
    with pytest.raises(DnsError, match="www.moui.io.*c.github.io.*--take-dns"):
        dns.apply(actions)
    assert prov.applied == []          # refuses before ANY change, not halfway


def test_replace_applied_with_take():
    dns, prov = _dns({"www.moui.io": [{"type": "CNAME", "values": ["c.github.io"]}]}, take=True)
    actions = dns.plan(["www.moui.io"], BOX)
    assert dns.refused(actions) == []
    dns.apply(actions)
    assert prov.applied == [("moui.io", ["www.moui.io"], BOX)]


def test_apply_calls_the_provider_once_per_zone():
    zones = {"moui.io": {"provider": "fake"}, "moui.co": {"provider": "fake"}}
    dns, prov = _dns({}, take=False, zones=zones)
    actions = dns.plan(["www.moui.io", "next.moui.co", "moui.io"], BOX)
    dns.apply(actions)
    assert prov.applied == [("moui.io", ["www.moui.io", "moui.io"], BOX),
                            ("moui.co", ["next.moui.co"], BOX)]


def test_apply_refuses_mixed_addresses():
    dns, prov = _dns({}, take=False)
    actions = [Action("www.moui.io", "moui.io", "create", (), BOX),
               Action("moui.io", "moui.io", "create", (), "1.2.3.4")]
    with pytest.raises(DnsError, match="differing addresses"):
        dns.apply(actions)
    assert prov.applied == []


@pytest.mark.parametrize("name", ["WWW.moui.io", "www.moui.io."])
def test_plan_refuses_unnormalised_names(name):
    dns, _ = _dns({}, take=False)
    with pytest.raises(DnsError, match="lowercase"):
        dns.plan([name], BOX)
