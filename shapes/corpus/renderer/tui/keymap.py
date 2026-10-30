# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The keymap: the renderer's capability registry and the declarative bindings
that map keys + footer labels to it. The navigation spine (arrows/tab/enter/
esc/q/?) is frame-owned and never appears here. A per-corpus bindings.yaml
overrides the shape default PER CAPABILITY; the merged result is then checked
against the reserved spine and itself in one pass, throwing loudly — no silent
override (the no-fallbacks rule, in the keymap). The footer is built from the
bindings' labels, so translating or rebinding is a file edit, never an app
change."""
import json
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
import yaml

# The capability registry for THIS slice. It grows by slice: the write slice
# adds confirm/dismiss/edit/tag/reprocess. A binding naming a capability not in
# this set throws now and works when the slice that registers it lands.
READ_CAPABILITIES = {"lens", "filter", "open-artifact", "ask", "assert"}

# The single-char keys the navigation spine owns. A binding may not steal them.
# (arrows/tab/enter/esc are multi-char Textual key names and the schema's
# 1-char `key` already prevents binding them; q and ? are the bindable chars
# the spine reserves.)
RESERVED_SPINE = {"q", "?"}

_SCHEMA = json.loads(
    (Path(__file__).parent / "bindings.v1.json").read_text())


class BindingError(Exception):
    """A keymap is invalid: an unknown capability, a reserved-key collision, or
    a key bound twice after the override merge."""


@dataclass(frozen=True)
class Binding:
    capability: str
    key: str
    label: str
    args: dict = field(default_factory=dict)


def _load_file(path: Path) -> list[dict]:
    doc = yaml.safe_load(path.read_text()) or {}
    raw = doc.get("bindings", [])
    for b in raw:
        jsonschema.validate(b, _SCHEMA)
    return raw


def load_bindings(default_path: Path, corpus_dir: Path,
                  registry: set) -> list[Binding]:
    """Load the shape default, merge a per-corpus bindings.yaml over it PER
    CAPABILITY, then check the merged set. Returns the merged bindings."""
    # Group default entries by capability; a capability may have multiple
    # bindings (e.g. lens has one per lens value).
    merged: dict[str, list[dict]] = {}
    for b in _load_file(default_path):
        merged.setdefault(b["capability"], []).append(b)

    override = corpus_dir / "bindings.yaml"
    if override.is_file():
        # Per-capability replace: all override entries for a capability replace
        # all default entries for that capability as a group.
        override_groups: dict[str, list[dict]] = {}
        for b in _load_file(override):
            override_groups.setdefault(b["capability"], []).append(b)
        for cap, entries in override_groups.items():
            merged[cap] = entries                # per-capability replace

    bindings = [Binding(b["capability"], b["key"], b["label"], b.get("args", {}))
                for entries in merged.values() for b in entries]
    _check(bindings, registry)
    return bindings


def _check(bindings: list, registry: set) -> None:
    seen_keys: dict[str, str] = {}
    for b in bindings:
        if b.capability not in registry:
            raise BindingError(
                f"binding for unknown capability {b.capability!r} "
                f"(registered: {sorted(registry)}); a capability registers when "
                "its slice lands")
        if b.key in RESERVED_SPINE:
            raise BindingError(
                f"binding {b.capability!r} uses key {b.key!r}, reserved by the "
                "navigation spine")
        if b.key in seen_keys:
            raise BindingError(
                f"key {b.key!r} bound twice: {seen_keys[b.key]!r} and {b.capability!r}")
        seen_keys[b.key] = b.capability


def footer_text(bindings: list) -> str:
    """The catalogue footer from the bindings' labels (the i18n seam) plus the
    frame-owned affordances. `filter` is the document screen's capability — it is
    not advertised here. The spine hints describe the focus model."""
    parts: list = []
    lens = sorted([b for b in bindings if b.capability == "lens"], key=lambda b: b.key)
    for b in lens:
        parts.append(f"{b.key} {b.label}")
    for b in bindings:
        if b.capability in ("lens", "filter"):
            continue
        parts.append(f"{b.key} {b.label}")
    parts += ["/ search", "tab plane", "↑/↓ move", "enter open", "q quit"]
    return "   ".join(parts)
