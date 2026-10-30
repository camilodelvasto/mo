# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
from datetime import datetime

import pytest

from corpus_server.gate.decide import decide


class _Ctr:
    def under_cap(self, i, r): return True
    def increment(self, i): pass


class _Lim:
    def check(self, ip, now): return (True, None)
    def record_401(self, ip, now): pass


def _decide(uri, role, roles, method="POST", counter=None):
    cfg = {"auth": {"scheme": "none"}, "default_role": role,
           "exposed_asks": ["converse", "explorar"], "roles": roles}
    return decide(cfg=cfg, access_list_path=None, counter=counter or _Ctr(), limiter=_Lim(),
                  ip="1.2.3.4", method=method, uri=uri, authorization=None,
                  now=datetime(2026, 6, 24))


def test_role_permits_its_ask():
    d = _decide("/ask/converse", "converse", {"converse": {"cap": 5, "asks": ["converse"]}})[0]
    assert d.status == 200


def test_role_denies_an_ask_outside_its_set():
    d = _decide("/ask/explorar", "converse", {"converse": {"cap": 5, "asks": ["converse"]}})[0]
    assert d.status == 403 and d.body == {"error": "ask_not_permitted"}


def test_role_without_asks_is_unrestricted():
    d = _decide("/ask/explorar", "open", {"open": {"cap": 5}})[0]   # no asks → all exposed
    assert d.status == 200


def test_box_exposure_precedes_role():
    # an ask the box doesn't expose at all is ask_not_exposed regardless of role
    d = _decide("/ask/ghost", "open", {"open": {"cap": 5, "asks": ["ghost"]}})[0]
    assert d.status == 403 and d.body == {"error": "ask_not_exposed"}


# --- attachment endpoints: exposure-gated, never metered -------------------------
# GET /ask/{name}/policy and POST /verify/{name} are the attachment seam. Both are
# gated like an ask (auth, exposed, role) but neither spends an LLM call, so neither
# touches the cap, and neither produces a ledger event.

class _CountingCtr(_Ctr):
    def __init__(self): self.increments = 0
    def under_cap(self, i, r): return False          # over cap: a metered call would 429
    def increment(self, i): self.increments += 1


def test_policy_read_is_allowed_for_an_exposed_ask_without_metering():
    ctr = _CountingCtr()
    d, event = _decide("/ask/converse/policy", "open", {"open": {"cap": 5}},
                       method="GET", counter=ctr)
    assert d.status == 200 and event is None and ctr.increments == 0


def test_policy_read_of_an_unexposed_ask_is_403():
    d, _ = _decide("/ask/ghost/policy", "open", {"open": {"cap": 5}}, method="GET")
    assert d.status == 403 and d.body == {"error": "ask_not_exposed"}


def test_verify_is_allowed_for_an_exposed_ask_without_metering():
    ctr = _CountingCtr()
    d, event = _decide("/verify/converse", "open", {"open": {"cap": 5}}, counter=ctr)
    assert d.status == 200 and event is None and ctr.increments == 0


def test_verify_respects_role_permission():
    d, _ = _decide("/verify/explorar", "converse",
                   {"converse": {"cap": 5, "asks": ["converse"]}})
    assert d.status == 403 and d.body == {"error": "ask_not_permitted"}


def test_get_on_the_ask_itself_is_still_refused():
    d, _ = _decide("/ask/converse", "open", {"open": {"cap": 5}}, method="GET")
    assert d.status == 403


# --- the route is the PATH, matched exactly -----------------------------------------
# The gate reads the route exactly as Caddy's handle_path forwards it (/api stripped),
# the same path serve routes. A route named anywhere else in the URI (a query value, a
# deeper path, a sibling endpoint, a doubled mount, a trailing slash serve redirects)
# names nothing: none may pass the gate, none may be metered.

@pytest.mark.parametrize("method,uri", [
    ("GET", "/doc/X/chunks?x=/ask/converse/policy"),
    ("GET", "/catalogue?x=/ask/converse/policy"),
    ("GET", "/events?x=/ask/converse/policy"),
    ("POST", "/ask/secret?x=/verify/converse"),
    ("POST", "/assert?x=/verify/converse"),
    ("POST", "/order?x=/ask/converse"),
    ("GET", "/ask/converse/policy/../../../catalogue"),
    ("POST", "/verify/converse/extra"),
    ("POST", "/ask/converse/policy"),
    ("POST", "/api/ask/converse"),
    ("POST", "/api/verify/converse"),
    ("GET", "/api/ask/converse/policy"),
])
def test_a_route_named_outside_the_path_names_nothing(method, uri):
    ctr = _CountingCtr()
    d, event = _decide(uri, "open", {"open": {"cap": 5}}, method=method, counter=ctr)
    assert d.status == 403 and d.body == {"error": "ask_not_exposed"}
    assert event is None and ctr.increments == 0


def test_a_query_on_a_real_ask_path_still_names_that_ask():
    d, event = _decide("/ask/converse?x=1", "open", {"open": {"cap": 5}})
    assert d.status == 200 and event["ask"] == "converse"


@pytest.mark.parametrize("uri", ["/ask/converse/", "/verify/converse/"])
def test_a_trailing_slash_is_not_the_route(uri):
    # serve answers a trailing slash with a redirect, never the ask: the gate must not meter it
    ctr = _CountingCtr()
    d, event = _decide(uri, "open", {"open": {"cap": 5}}, counter=ctr)
    assert d.status == 403 and d.body == {"error": "ask_not_exposed"}
    assert event is None and ctr.increments == 0
