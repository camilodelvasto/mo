# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import json
import subprocess
import pytest
from cli.infra.dns import DnsError, resolve_provider
from cli.infra.dns import route53

SPEC = {"provider": "route53", "aws_profile": "default"}
PUBLIC = {"PrivateZone": False}
ZONES = {"HostedZones": [{"Id": "/hostedzone/Z1", "Name": "moui.io.", "Config": PUBLIC}]}
SETS = {"ResourceRecordSets": [
    {"Name": "www.moui.io.", "Type": "CNAME", "TTL": 300,
     "ResourceRecords": [{"Value": "example.github.io"}]},
    {"Name": "www.moui.io.", "Type": "TXT", "TTL": 300, "ResourceRecords": [{"Value": "\"x\""}]},
    {"Name": "x.www.moui.io.", "Type": "A", "TTL": 300, "ResourceRecords": [{"Value": "1.1.1.1"}]},
]}
ALIAS = {"Name": "moui.io.", "Type": "A",
         "AliasTarget": {"DNSName": "d1.cloudfront.net.", "HostedZoneId": "Z2",
                         "EvaluateTargetHealth": False}}


def _fake(monkeypatch, responses):
    calls = []
    def aws(args, profile, **kw):
        calls.append((args, profile, kw))
        return responses[args[1]]
    monkeypatch.setattr(route53, "_aws", aws)
    return calls


def test_registry_resolves_route53():
    assert resolve_provider("route53") is route53


def test_records_filters_exact_name_and_address_types(monkeypatch):
    calls = _fake(monkeypatch, {"list-hosted-zones-by-name": ZONES,
                                "list-resource-record-sets": SETS})
    recs = route53.records("moui.io", "www.moui.io", SPEC)
    assert [(r["type"], r["values"]) for r in recs] == [("CNAME", ["example.github.io"])]
    lst = next(a for a, _, _ in calls if a[1] == "list-resource-record-sets")
    assert lst[lst.index("--hosted-zone-id") + 1] == "/hostedzone/Z1"
    assert lst[lst.index("--start-record-name") + 1] == "www.moui.io"
    zones = next(a for a, _, _ in calls if a[1] == "list-hosted-zones-by-name")
    assert "--max-items" not in zones


def test_alias_records_are_described_not_dropped(monkeypatch):
    _fake(monkeypatch, {"list-hosted-zones-by-name": ZONES,
                        "list-resource-record-sets": {"ResourceRecordSets": [ALIAS]}})
    assert route53.records("moui.io", "moui.io", SPEC)[0]["values"] == ["ALIAS:d1.cloudfront.net."]


def test_zone_not_found_throws(monkeypatch):
    _fake(monkeypatch, {"list-hosted-zones-by-name": {"HostedZones": [
        {"Id": "/hostedzone/Z9", "Name": "moui.ai.", "Config": PUBLIC}]}})
    with pytest.raises(DnsError, match="0 public Route53 hosted zones named moui.io"):
        route53.records("moui.io", "www.moui.io", SPEC)


def test_private_zone_is_refused(monkeypatch):
    _fake(monkeypatch, {"list-hosted-zones-by-name": {"HostedZones": [
        {"Id": "/hostedzone/Z1", "Name": "moui.io.", "Config": {"PrivateZone": True}}]}})
    with pytest.raises(DnsError, match="0 public Route53 hosted zones named moui.io"):
        route53.records("moui.io", "www.moui.io", SPEC)


def test_duplicate_public_zones_are_refused(monkeypatch):
    _fake(monkeypatch, {"list-hosted-zones-by-name": {"HostedZones": [
        {"Id": "/hostedzone/Z1", "Name": "moui.io.", "Config": PUBLIC},
        {"Id": "/hostedzone/Z2", "Name": "moui.io.", "Config": PUBLIC}]}})
    with pytest.raises(DnsError, match="2 public Route53 hosted zones named moui.io"):
        route53.records("moui.io", "www.moui.io", SPEC)


def test_truncated_listing_still_on_the_name_throws(monkeypatch):
    page = {"ResourceRecordSets": SETS["ResourceRecordSets"][:2], "NextToken": "t"}
    _fake(monkeypatch, {"list-hosted-zones-by-name": ZONES, "list-resource-record-sets": page})
    with pytest.raises(DnsError, match="www.moui.io.*truncated"):
        route53.records("moui.io", "www.moui.io", SPEC)


def test_truncated_listing_past_the_name_is_complete_for_it(monkeypatch):
    # Sets come back in Route53 order from --start-record-name: once a page holds a
    # set for another name, every set of this name has been seen.
    page = dict(SETS, IsTruncated=True)
    _fake(monkeypatch, {"list-hosted-zones-by-name": ZONES, "list-resource-record-sets": page})
    assert len(route53.records("moui.io", "www.moui.io", SPEC)) == 1


def test_missing_response_key_is_a_named_failure(monkeypatch):
    _fake(monkeypatch, {"list-hosted-zones-by-name": {}})
    with pytest.raises(DnsError, match="list-hosted-zones-by-name.*HostedZones"):
        route53.records("moui.io", "www.moui.io", SPEC)


def test_missing_profile_throws():
    with pytest.raises(DnsError, match="aws_profile"):
        route53.records("moui.io", "www.moui.io", {"provider": "route53"})


def _run_returning(monkeypatch, stdout):
    monkeypatch.setattr(route53.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, stdout=stdout, stderr=""))


def test_empty_output_throws_unless_the_caller_expects_none(monkeypatch):
    _run_returning(monkeypatch, "")
    with pytest.raises(DnsError, match="list-hosted-zones-by-name.*no output"):
        route53._aws(["route53", "list-hosted-zones-by-name"], "default")
    assert route53._aws(["route53", "wait"], "default", expect_output=False) == {}


def test_apply_is_one_batch_delete_then_create_and_waits(monkeypatch):
    calls = _fake(monkeypatch, {"list-hosted-zones-by-name": ZONES,
                                "change-resource-record-sets": {"ChangeInfo": {"Id": "/change/C1"}},
                                "wait": {}})
    cname = {"type": "CNAME", "values": ["example.github.io"], "raw": SETS["ResourceRecordSets"][0]}
    route53.apply("moui.io", [("www.moui.io", [cname])], "203.0.113.7", SPEC)
    change_args = next(a for a, _, _ in calls if a[1] == "change-resource-record-sets")
    batch = json.loads(change_args[change_args.index("--change-batch") + 1])
    assert [c["Action"] for c in batch["Changes"]] == ["DELETE", "CREATE"]
    assert batch["Changes"][0]["ResourceRecordSet"] == SETS["ResourceRecordSets"][0]
    assert batch["Changes"][1]["ResourceRecordSet"] == {
        "Name": "www.moui.io.", "Type": "A", "TTL": 300,
        "ResourceRecords": [{"Value": "203.0.113.7"}]}
    wait_args, _, wait_kw = next(c for c in calls if c[0][1] == "wait")
    assert wait_args[-2:] == ["--id", "/change/C1"]
    assert wait_kw == {"expect_output": False}
    assert all(p == "default" for _, p, _ in calls)


def test_apply_deletes_an_alias_raw_unchanged(monkeypatch):
    calls = _fake(monkeypatch, {"list-hosted-zones-by-name": ZONES,
                                "change-resource-record-sets": {"ChangeInfo": {"Id": "/change/C1"}},
                                "wait": {}})
    alias = {"type": "A", "values": ["ALIAS:d1.cloudfront.net."], "raw": ALIAS}
    route53.apply("moui.io", [("moui.io", [alias])], "203.0.113.7", SPEC)
    change_args = next(a for a, _, _ in calls if a[1] == "change-resource-record-sets")
    batch = json.loads(change_args[change_args.index("--change-batch") + 1])
    assert batch["Changes"][0] == {"Action": "DELETE", "ResourceRecordSet": ALIAS}


def test_apply_moves_every_name_of_a_zone_in_one_batch(monkeypatch):
    calls = _fake(monkeypatch, {"list-hosted-zones-by-name": ZONES,
                                "change-resource-record-sets": {"ChangeInfo": {"Id": "/change/C1"}},
                                "wait": {}})
    cname = {"type": "CNAME", "values": ["example.github.io"], "raw": SETS["ResourceRecordSets"][0]}
    alias = {"type": "A", "values": ["ALIAS:d1.cloudfront.net."], "raw": ALIAS}
    route53.apply("moui.io", [("www.moui.io", [cname]), ("moui.io", [alias])],
                  "203.0.113.7", SPEC)
    changes = [a for a, _, _ in calls if a[1] == "change-resource-record-sets"]
    assert len(changes) == 1
    assert len([a for a, _, _ in calls if a[1] == "wait"]) == 1
    batch = json.loads(changes[0][changes[0].index("--change-batch") + 1])
    assert [(c["Action"], c["ResourceRecordSet"]["Name"]) for c in batch["Changes"]] == [
        ("DELETE", "www.moui.io."), ("CREATE", "www.moui.io."),
        ("DELETE", "moui.io."), ("CREATE", "moui.io.")]


def test_apply_with_no_changes_is_a_contract_error():
    with pytest.raises(DnsError, match="no changes"):
        route53.apply("moui.io", [], "203.0.113.7", SPEC)
