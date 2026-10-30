# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""DNS as a pluggable capability. infrastructure/dns.yaml declares which provider
owns each zone; a deploy plans over its names, then applies the plan. The
decision — keep / create / replace — is one pure function shared by every
provider. A replace (the name points somewhere that is not this box) is refused
unless the operator passed --take-dns for this run, and the refusal happens
before any change. No fallbacks: an undeclared zone or provider throws."""
import importlib
from dataclasses import dataclass
from pathlib import Path

import yaml


class DnsError(Exception):
    pass


@dataclass(frozen=True)
class Action:
    name: str
    zone: str
    kind: str          # keep | create | replace
    current: tuple     # the provider's records; opaque outside the provider
    address: str       # where the plan points the name


def load_zones(corpus_root: Path) -> dict:
    f = corpus_root / "infrastructure" / "dns.yaml"
    if not f.is_file():
        raise DnsError(f"no {f} — declare the zones a deploy may write "
                       f"(zones: {{<zone>: {{provider: route53, aws_profile: ...}}}})")
    raw = yaml.safe_load(f.read_text())
    if not isinstance(raw, dict):
        raise DnsError(f"{f}: top level must be a mapping with a zones key")
    if "zones" not in raw or raw["zones"] is None:
        raise DnsError(f"{f}: no zones declared")
    zones = raw["zones"]
    if not isinstance(zones, dict):
        raise DnsError(f"{f}: zones must be a mapping of <zone>: {{provider: ...}}")
    if not zones:
        raise DnsError(f"{f}: no zones declared")
    for zone, spec in zones.items():
        if not spec or "provider" not in spec:
            raise DnsError(f"zone {zone} declares no provider in {f}")
    return zones


def zone_for(name: str, zones: dict) -> str:
    matches = [z for z in zones if name == z or name.endswith("." + z)]
    if not matches:
        raise DnsError(f"{name} is in no zone declared in infrastructure/dns.yaml "
                       f"(declared: {', '.join(sorted(zones))})")
    return max(matches, key=len)


def decide(current: list, address: str) -> str:
    if not current:
        return "create"
    if len(current) == 1 and current[0]["type"] == "A" and current[0]["values"] == [address]:
        return "keep"
    return "replace"


def resolve_provider(name: str):
    try:
        mod = importlib.import_module(f"cli.infra.dns.{name}")
    except ModuleNotFoundError as e:
        # Only the provider module itself missing means "unknown". A provider whose
        # own dependency is missing must surface as that dependency, not be masked.
        if e.name != f"cli.infra.dns.{name}":
            raise
        raise DnsError(f"unknown dns provider {name!r} — no cli/infra/dns/{name}.py") from None
    for fn in ("records", "apply"):
        if not hasattr(mod, fn):
            raise DnsError(f"dns provider {name!r} has no {fn}()")
    return mod


def _describe(current: tuple) -> str:
    return ", ".join(f"{r['type']} {' '.join(r['values'])}" for r in current)


class Dns:
    def __init__(self, zones: dict, *, take: bool, resolve=resolve_provider):
        self._zones, self._take, self._resolve = zones, take, resolve

    def _provider(self, zone: str):
        spec = self._zones[zone]
        return self._resolve(spec["provider"]), spec

    def plan(self, names: list, address: str) -> list:
        actions = []
        for name in names:
            # Names arrive normalised; a mixed-case or rooted name would compare
            # unequal to the provider's records and plan a wrong change.
            if name != name.lower() or name.endswith("."):
                raise DnsError(f"dns name {name!r} must be lowercase with no trailing dot")
            zone = zone_for(name, self._zones)
            mod, spec = self._provider(zone)
            current = tuple(mod.records(zone, name, spec))
            actions.append(Action(name, zone, decide(list(current), address), current, address))
        return actions

    def refused(self, actions: list) -> list:
        return [] if self._take else [a for a in actions if a.kind == "replace"]

    def apply(self, actions: list) -> None:
        addresses = sorted({a.address for a in actions})
        if len(addresses) > 1:
            raise DnsError(f"one apply points every name at one address — actions carry "
                           f"differing addresses: {', '.join(addresses)}")
        refused = self.refused(actions)
        if refused:
            listed = "; ".join(f"{a.name} → {_describe(a.current)}" for a in refused)
            raise DnsError(f"DNS points elsewhere: {listed} — rerun with --take-dns "
                           f"to point it at {refused[0].address}")
        # One provider call per zone: every name of a zone moves together or not at all.
        by_zone: dict = {}
        for a in actions:
            if a.kind != "keep":
                by_zone.setdefault(a.zone, []).append((a.name, list(a.current)))
        for zone, changes in by_zone.items():
            mod, spec = self._provider(zone)
            mod.apply(zone, changes, addresses[0], spec)
