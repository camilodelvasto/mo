# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The pure stack rule: which GENERATION capabilities the exposed asks declare.
No IO — a local read of ask.yaml's shape — which is why it is the rail's, not the
mechanism adapter's. Generation lives in BOTH synthesize.uses and decompose.uses
(converse/explorar reach api.claude only via decompose; a synthesize-only read
silently misses it). Retrieval/embedder caps are the sync passport's job, not
this rule (the deploy-generation / sync-embedder seam)."""
from pathlib import Path


MEDIA_IMAGE = "media.image"   # the /verify canonicalizer an attachments ask needs


def _exposed(ask_yaml: dict, exposed_asks: list) -> list:
    by_id = {a["id"]: a for a in ask_yaml.get("asks", [])}
    out = []
    for name in exposed_asks:
        ask = by_id.get(name)
        if ask is None:
            raise ValueError(f"exposed ask {name!r} is not defined in ask.yaml")
        out.append(ask)
    return out


def required_caps(ask_yaml: dict, exposed_asks: list) -> set:
    caps = set()
    for ask in _exposed(ask_yaml, exposed_asks):
        for step in ("synthesize", "decompose"):
            uses = ask.get(step, {}).get("uses")
            if uses:
                caps.add(uses)
        # `attachments:` names no capability, but declares the need for one: /verify
        # runs media.image on every upload. The declaration IS the requirement.
        if ask.get("attachments"):
            caps.add(MEDIA_IMAGE)
    return caps


def attest_required(ask_yaml: dict, exposed_asks: list) -> bool:
    """Does the box have to hold an attest secret? True when an exposed ask accepts
    attachments — the box signs every canonical image with it, and /verify cannot
    answer without one."""
    return any(ask.get("attachments") for ask in _exposed(ask_yaml, exposed_asks))


def bound_caps(capabilities: dict) -> set:
    """The capability keys a parsed capabilities.yaml binds."""
    return set((capabilities or {}).get("capabilities", {}).keys())


def shims_present(capabilities: dict, corpus_root: Path) -> None:
    """Cap declared != cap runnable: every run[0] under /app/bin/ must have a
    matching file in bin/ (and so in the serve image via `COPY bin /app/bin`).
    Else the binding compare passes but the serve dies at first ask 'no such file'."""
    for name, binding in (capabilities or {}).get("capabilities", {}).items():
        # Both verbs spawn a process: a stream-only binding (the vision capability has
        # no run:) needs its shim just as much.
        for verb in ("run", "stream"):
            argv = binding.get(verb) or []
            if not argv:
                continue
            target = argv[0]
            if not target.startswith("/app/bin/"):
                continue
            shim = target[len("/app/bin/"):]
            if not (corpus_root / "bin" / shim).exists():
                raise ValueError(
                    f"capability {name!r} binds {target} but bin/{shim} is not in "
                    f"the repo — it won't be in the image; the serve would fail at "
                    f"first ask. Add the shim to bin/ or fix the binding.")
