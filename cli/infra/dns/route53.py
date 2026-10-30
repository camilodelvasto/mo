# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Route53 provider for the dns capability. Shells the aws CLI with the zone's
declared profile — the same posture as cli/deploy/aws_creds.py. apply() sends one
batch per zone (DELETE each name's current sets + CREATE its A record), so a
CNAME→A switch is atomic and www + apex move together or not at all; it then
blocks until Route53 reports the change INSYNC on its authoritative servers: the
point at which an ACME validation can see it. No silent empties: a missing
response key, empty output, an ambiguous zone or a cut listing throws."""
import json
import subprocess

from cli.infra.dns import DnsError

_ADDRESS_TYPES = ("A", "AAAA", "CNAME")
TTL = 300


def _aws(args: list, profile: str, *, expect_output: bool = True) -> dict:
    r = subprocess.run(["aws", *args, "--profile", profile, "--output", "json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise DnsError(f"aws {' '.join(args[:2])} failed: {r.stderr.strip()}")
    if not r.stdout.strip():
        if expect_output:
            raise DnsError(f"aws {' '.join(args[:2])} returned no output")
        return {}
    return json.loads(r.stdout)


def _field(out: dict, key: str, call: str):
    if key not in out:
        raise DnsError(f"aws route53 {call}: response has no {key}")
    return out[key]


def _profile(spec: dict) -> str:
    if not spec.get("aws_profile"):
        raise DnsError("route53 zone declares no aws_profile in infrastructure/dns.yaml")
    return spec["aws_profile"]


def _zone_id(zone: str, profile: str) -> str:
    call = "list-hosted-zones-by-name"
    out = _aws(["route53", call, "--dns-name", zone], profile)
    found = [z for z in _field(out, "HostedZones", call)
             if z["Name"] == zone + "." and not z["Config"]["PrivateZone"]]
    if len(found) != 1:
        raise DnsError(f"{len(found)} public Route53 hosted zones named {zone} under "
                       f"aws profile {profile!r} — need exactly one")
    return found[0]["Id"]


def records(zone: str, name: str, spec: dict) -> list:
    profile = _profile(spec)
    call = "list-resource-record-sets"
    out = _aws(["route53", call, "--hosted-zone-id", _zone_id(zone, profile),
                "--start-record-name", name, "--max-items", "10"], profile)
    sets = _field(out, "ResourceRecordSets", call)
    # Sets come back in Route53 order from --start-record-name, so this name's sets
    # are contiguous at the front. A cut page is complete for the name only if it
    # already reached a set of another name; otherwise refuse — never decide on a
    # partial view.
    truncated = "NextToken" in out or out.get("IsTruncated") is True
    if truncated and all(rs["Name"] == name + "." for rs in sets):
        raise DnsError(f"Route53 listing for {name} in {zone} is truncated before its "
                       f"record sets end")
    found = []
    for rs in sets:
        if rs["Name"] != name + "." or rs["Type"] not in _ADDRESS_TYPES:
            continue
        if "AliasTarget" in rs:
            values = [f"ALIAS:{rs['AliasTarget']['DNSName']}"]
        else:
            values = [r["Value"] for r in rs["ResourceRecords"]]
        found.append({"type": rs["Type"], "values": values, "raw": rs})
    return found


def apply(zone: str, changes: list, address: str, spec: dict) -> None:
    """changes: [(name, current)] — every name of this zone that moves, in one batch."""
    if not changes:
        raise DnsError(f"route53 apply for {zone} called with no changes")
    profile = _profile(spec)
    batch_changes = []
    for name, current in changes:
        batch_changes += [{"Action": "DELETE", "ResourceRecordSet": r["raw"]} for r in current]
        batch_changes.append({"Action": "CREATE", "ResourceRecordSet": {
            "Name": name + ".", "Type": "A", "TTL": TTL,
            "ResourceRecords": [{"Value": address}]}})
    names = ", ".join(n for n, _ in changes)
    batch = {"Comment": f"mo deploy: {names} -> {address}", "Changes": batch_changes}
    call = "change-resource-record-sets"
    out = _aws(["route53", call, "--hosted-zone-id", _zone_id(zone, profile),
                "--change-batch", json.dumps(batch)], profile)
    change_id = _field(_field(out, "ChangeInfo", call), "Id", call)
    _aws(["route53", "wait", "resource-record-sets-changed", "--id", change_id],
         profile, expect_output=False)
