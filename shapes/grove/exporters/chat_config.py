# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The single source of truth for the chat-config island, emitted identically by
the dev shell (server.py) and the static build (compose.py) so chat.js reads the
same shape in both. The blob is {endpoint, gate?, chats}; chats is keyed by the
page's mount route with per-chat presentation. Drift between dev and static here
is the worst failure (works in `mo grove serve`, breaks deployed), so both call
this one function."""
import json
from render import _md   # the trusted live-HTML markdown renderer (same one dev uses)


def chat_presentation(grove: dict, pages, ctx: dict) -> dict:
    """Per-chat presentation the client renders before the first turn, keyed by the
    **mount route of the page** that mounts each chat feature (matching `data-route`).

    Features are routeless; a `pages:` entry mounts one in its `body` (`feature: id`),
    and the page's route is the prefix the chat owns. Presentation (persist/name/avatar/
    intro) stays on the **feature** — the bot's identity travels with the capability; the
    page only decides where it mounts. Built at serve time and baked into #chat-config
    (NOT runtime-fetched). intro markdown → HTML via the build renderer (the one trusted
    live-HTML payload). Absent intro/avatar/name → omitted. persist echoes the feature's
    declaration; an unknown value fails the build (see build.py).
    """
    base_path = ctx["base_path"] if ctx else ""
    chat_features = {f.get("id"): f for f in grove.get("features", [])
                     if f.get("type") == "chat"}
    chats = {}
    for page in pages:
        for item in page.get("body", []):
            if not (isinstance(item, dict) and "feature" in item):
                continue
            feature = chat_features.get(item["feature"])
            if feature is None:
                continue  # not a chat feature (the composer validates the ref itself)
            base = page["route"].rstrip("/") + "/"
            entry = {"ask": feature["ask"], "persist": feature.get("persist", "none")}
            name = feature.get("name")
            if name:
                entry["name"] = name
            avatar = feature.get("avatar")
            if avatar:
                # Root-relative so deep links (/chatbot/<slug>/) don't resolve it against
                # the current path. Absolute URL passes through; "/x" is already root-
                # relative; bare "assets/x" follows the grove asset convention → "/assets/x".
                if avatar.startswith(("http://", "https://", "//")):
                    entry["avatar"] = avatar
                elif avatar.startswith("/"):
                    entry["avatar"] = base_path + avatar
                else:
                    entry["avatar"] = base_path + "/" + avatar
            intro = feature.get("intro")
            if intro:
                entry["intro_html"] = _md.render(intro)
            instructions = feature.get("instructions")
            if instructions:
                body = instructions.get("body")
                if not body:
                    raise ValueError(f"chat feature {feature.get('id')!r}: "
                                     "instructions declared without a body")
                entry["instructions_html"] = _md.render(body)
                entry["instructions_collapsible"] = bool(instructions.get("collapsible", False))
                if instructions.get("summary"):
                    entry["instructions_summary"] = instructions["summary"]
            chats[base] = entry
    return chats


def emit_chat_config(grove: dict, pages, ctx: dict, *, endpoint: str,
                     gate: dict | None) -> str:
    """The two <script> lines to insert before </head>, identical in dev + static.
    The blob is {endpoint, gate?, chats}. `gate` (when present) is
    {scheme, check}; NO secret is ever placed here — the secret is presented by
    the user at runtime, never baked into the page."""
    cfg = {"endpoint": endpoint, "grove_key": ctx["base_path"],
           "chats": chat_presentation(grove, pages, ctx)}
    if gate is not None:
        cfg["gate"] = gate
    blob = json.dumps(cfg, ensure_ascii=False)
    return (f'    <script type="application/json" id="chat-config">{blob}</script>\n'
            f'    <script src="/vendor/markdown-it.min.js" defer></script>\n')
