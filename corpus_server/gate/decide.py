# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The four-check decision, pure. The app wires config + counter + limiter + the
access list path in; this returns a Decision and, on 200, the ask event the app
must append before incrementing. Order: IP rate → verify → ask exposed → cap."""
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from corpus_server.gate.verifiers import verify_access_code

# Engine routes, matched EXACTLY against the request's route (see _route) — never
# searched for inside the raw URI, where a query value could name one. The route is
# the path serve routes: what Caddy's handle_path forwards, /api already stripped.
_ASK = re.compile(r"/ask/([^/]+)")
# The attachment seam: reading an ask's declared policy and verifying an image for
# it. Gated like the ask (auth, exposed, role) but never metered — no LLM spend.
_POLICY = re.compile(r"/ask/([^/]+)/policy")
_VERIFY = re.compile(r"/verify/([^/]+)")
_CHECK_PATH = "/api/check"


def _route(uri: str) -> str:
    """The engine route a forwarded URI names: the path before the query, exactly as
    Caddy's handle_path forwards it (/api stripped) — the same path serve routes. No
    mount stripping, no trailing-slash tolerance: a path serve would not answer as an
    ask is not an ask, so the gate never meters it."""
    return uri.split("?", 1)[0]


@dataclass
class Decision:
    status: int
    body: dict
    headers: dict = field(default_factory=dict)


def parse_ask_name(method: str, uri: str) -> str | None:
    if method.upper() != "POST":
        return None
    m = _ASK.fullmatch(_route(uri))
    return m.group(1) if m else None


def parse_unmetered_ask_name(method: str, uri: str) -> str | None:
    """The ask an unmetered attachment request is about, or None if this is not one."""
    method = method.upper()
    if method == "GET":
        m = _POLICY.fullmatch(_route(uri))
    elif method == "POST":
        m = _VERIFY.fullmatch(_route(uri))
    else:
        return None
    return m.group(1) if m else None


def decide(*, cfg: dict, access_list_path: Path | None, counter, limiter,
           ip: str, method: str, uri: str, authorization: str | None,
           now: datetime) -> tuple[Decision, dict | None]:
    ok, retry_after = limiter.check(ip, now)
    if not ok:
        return Decision(429, {"error": "rate_limited"},
                        {"Retry-After": str(retry_after)}), None

    scheme = cfg["auth"]["scheme"]
    if scheme == "access-code":
        ident = verify_access_code(authorization, access_list_path, cfg["roles"])
        if ident is None:
            limiter.record_401(ip, now)
            return Decision(401, {"error": "unauthorized"}), None
        identity, role = ident
    else:                                    # none: the IP is the identity
        identity, role = ip, cfg["default_role"]

    # Credential pre-check: the secret is CURRENTLY ACCEPTED — not a promise the
    # next ask will be served. Rides the per-minute limit (checked above) and
    # record_401 on bad codes, but never touches the monthly cap (no event, no
    # increment). Placed after auth so an invalid code is a normal 401.
    if uri.split("?", 1)[0].rstrip("/") == _CHECK_PATH:
        return Decision(200, {}, {}), None

    unmetered = parse_unmetered_ask_name(method, uri)
    name = unmetered if unmetered is not None else parse_ask_name(method, uri)
    if name is None or name not in cfg["exposed_asks"]:
        return Decision(403, {"error": "ask_not_exposed"}), None

    role_asks = cfg["roles"][role].get("asks")           # None = unrestricted
    if role_asks is not None and name not in role_asks:
        return Decision(403, {"error": "ask_not_permitted"}), None

    if unmetered is not None:                # policy read / verify: no cap, no event
        return Decision(200, {}, {"X-Identity": identity}), None

    if not counter.under_cap(identity, role):
        return Decision(429, {"error": "quota_exceeded"}), None

    counter.increment(identity)
    event = {"event": "ask", "id": identity, "ask": name, "ts": now.isoformat()}
    return Decision(200, {}, {"X-Identity": identity}), event
