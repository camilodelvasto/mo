# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Resolve a grove's chat-feature dependency on a remote ask API BY REFERENCE.

The grove deploy target declares `services.chat: corpus-server/<name>` (a box
target ref, never a URL) and a `credential:` (a gitignored secret path). This
reads exactly two fields across the reference — `domain` and `auth.scheme` —
and derives one ChatBinding: the ask endpoint, the gate block {scheme, check}
(when scheme is 'access-code'), the CSP origins (one per chat feature, all
origin_of(endpoint)), and the probe code from the secret.

`auth` stops at this resolver — it does NOT appear in the returned binding.
Env is inherited: the grove's deploy env resolves the box target's MATCHING env.
Three distinct named throws, each a different operator mistake."""
from pathlib import Path

import yaml

from cli.infra.origin import origin_of
from cli.infra.targets import load_target, get_environment, TargetError


class ChatBindingError(Exception):
    pass


def _read_secret_code(credential_path: str, corpus_root: Path) -> str:
    """Read the access code from a gitignored secret file. The code is a public,
    revocable token (its protection is rate-limit + revocation, not secrecy), but
    it must never live in authoring source — so it is read from secrets/ here and
    injected into the build, never committed. Fail loud if absent."""
    f = corpus_root / credential_path
    if not f.is_file():
        raise ChatBindingError(
            f"chat credential secret not found: {credential_path} — "
            f"create it (it holds the access code; gitignored, never committed)")
    data = yaml.safe_load(f.read_text()) or {}
    code = data.get("access_code") or data.get("code")
    if not code:
        raise ChatBindingError(
            f"chat credential {credential_path} has no 'access_code' — "
            f"never bake an empty credential")
    return code


def _check_persistable(grove: dict, box_env: dict, ref: str, corpus_root: Path) -> None:
    """A `persist: local` chat stores a conversation under the name the box streams in
    its `title` event, and only a `titled: true` ask emits one. Without it the chat
    runs and silently stores nothing — so the mismatch is refused here, where the
    grove's declaration meets the box's, instead of in a visitor's browser."""
    persistent = [f for f in grove.get("features", [])
                  if f.get("type") == "chat" and f.get("persist") == "local"]
    if not persistent:
        return
    if "content" not in box_env:
        raise ChatBindingError(
            f"grove has persist: local chat(s) {[f['id'] for f in persistent]} but the "
            f"box env '{ref}' declares no 'content' — without its ask.yaml there is no "
            f"way to tell whether those asks can name a conversation")
    ask_path = corpus_root / box_env["content"] / "ask.yaml"
    if not ask_path.is_file():
        raise ChatBindingError(f"box env '{ref}' declares content {box_env['content']} "
                               f"but {ask_path} is not there")
    asks = {a["id"]: a for a in (yaml.safe_load(ask_path.read_text()) or {}).get("asks", [])}
    for f in persistent:
        ask = asks.get(f["ask"])
        if ask is None:
            raise ChatBindingError(
                f"chat '{f['id']}' names ask '{f['ask']}', which {ask_path} does not define")
        if not ask.get("synthesize", {}).get("titled"):
            raise ChatBindingError(
                f"chat '{f['id']}' declares persist: local but ask '{f['ask']}' is not "
                f"titled — the client names a conversation from the box's title event, "
                f"so nothing would ever be stored. Add `titled: true` to the ask's "
                f"synthesize block, or set persist: none")


def resolve_chat_binding(grove: dict, grove_env: dict, env_name: str,
                         corpus_root: Path, *, with_code: bool = True) -> dict:
    chat_ids = [f["id"] for f in grove.get("features", []) if f.get("type") == "chat"]
    if not chat_ids:
        return {"endpoint": None, "gate": None, "code": None, "feature_endpoints": {}}   # no chat: nothing to bind

    # Throw 1 — feature declared, binding absent.
    ref = (grove_env.get("services") or {}).get("chat")
    if not ref:
        raise ChatBindingError(
            f"grove declares chat feature(s) {chat_ids} but its deploy target's "
            f"env '{env_name}' has no services.chat")

    # Throw 2 — the referenced box target doesn't exist.
    try:
        box_target = load_target(ref, corpus_root)
    except TargetError as e:
        raise ChatBindingError(
            f"services.chat references '{ref}' — no such target ({e})")

    # Throw 3 — box target exists but no matching env (env-inherited).
    try:
        box_env = get_environment(box_target, env_name)
    except TargetError:
        raise ChatBindingError(
            f"grove env '{env_name}' found no '{env_name}' env in '{ref}' — "
            f"shared env vocabulary, matched by name (you may not have defined "
            f"the {env_name} box yet)")

    _check_persistable(grove, box_env, ref, corpus_root)

    domain = box_env["domain"]                       # field 1 of 2 read across the reference
    scheme_url = "http" if box_env.get("local") else "https"   # local: true → plain http for dev
    endpoint = f"{scheme_url}://{domain}/api"
    origin = origin_of(endpoint)

    scheme = (box_env.get("auth") or {}).get("scheme")   # field 2 of 2 — the seam
    if scheme == "access-code":
        gate = {"scheme": "access-code", "check": f"{scheme_url}://{domain}/api/check"}
        code = _read_secret_code(grove_env["credential"], corpus_root) if with_code else None   # probe-only when with_code; dev derives the gate without it, never published
    elif scheme == "none":
        gate, code = None, None
    else:
        raise ChatBindingError(
            f"services.chat box env declares unknown auth scheme {scheme!r} "
            f"(expected 'access-code' or 'none')")

    return {"endpoint": endpoint, "gate": gate, "code": code,
            "feature_endpoints": {fid: origin for fid in chat_ids}}
