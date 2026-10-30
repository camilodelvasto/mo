# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

UTC = timezone.utc


def _gate_yaml(tmp_path, **over):
    cfg = {
        "upstream": "http://serve:8080",
        "ledger": str(tmp_path / "ledger.jsonl"),
        "exposed_asks": ["chat", "search"],
        "auth": {"scheme": "access-code", "access_list": str(tmp_path / "access.csv")},
        "roles": {"standard": {"cap": 2}, "trial": {"cap": 1}},
        "default_role": "standard",
        "window": "month",
        "rate_limit": {"per_minute": 3, "block_after": 2, "block_for": "15m"},
    }
    cfg.update(over)
    p = tmp_path / "gate.yaml"
    p.write_text(yaml.dump(cfg))
    return p


def test_load_gate_config_rejects_undefined_default_role(tmp_path):
    from corpus_server.gate.config import load_gate_config
    p = _gate_yaml(tmp_path, default_role="ghost")
    with pytest.raises(ValueError, match="default_role"):
        load_gate_config(p)


def test_load_gate_config_names_missing_rate_limit_inner_key(tmp_path):
    # a misspelled/missing inner key must fail at load with a named error,
    # not later as a bare KeyError in create_gate
    from corpus_server.gate.config import load_gate_config
    p = _gate_yaml(tmp_path, rate_limit={"block_after": 2, "block_for": "15m"})  # no per_minute
    with pytest.raises(ValueError, match="rate_limit missing 'per_minute'"):
        load_gate_config(p)


def test_load_gate_config_names_role_missing_cap(tmp_path):
    from corpus_server.gate.config import load_gate_config
    p = _gate_yaml(tmp_path, roles={"standard": {}})  # role without a cap
    with pytest.raises(ValueError, match="role 'standard' missing 'cap'"):
        load_gate_config(p)


def _access_csv(tmp_path):
    p = tmp_path / "access.csv"
    p.write_text("id,code,role,active\n"
                 "elections-team,a1b2c3,standard,true\n"
                 "revoked,g7h8i9,standard,false\n")
    return p


def test_verify_access_code_active_row(tmp_path):
    from corpus_server.gate.verifiers import verify_access_code
    roles = {"standard": {"cap": 2}}
    assert verify_access_code("Bearer a1b2c3", _access_csv(tmp_path), roles) == ("elections-team", "standard")


def test_verify_access_code_rejects_inactive_and_unknown(tmp_path):
    from corpus_server.gate.verifiers import verify_access_code
    roles = {"standard": {"cap": 2}}
    p = _access_csv(tmp_path)
    assert verify_access_code("Bearer g7h8i9", p, roles) is None       # inactive
    assert verify_access_code("Bearer nope", p, roles) is None         # unknown
    assert verify_access_code(None, p, roles) is None                  # absent


def test_ledger_rolls_per_month_and_reads_ask_events(tmp_path):
    from corpus_server.gate import ledger
    base = tmp_path / "ledger.jsonl"
    now = datetime(2026, 6, 16, 9, 14, tzinfo=UTC)
    path = ledger.window_path(base, "month", now)
    assert path.name == "ledger-2026-06.jsonl"
    ledger.append(path, {"event": "ask", "id": "elections-team", "ask": "chat", "ts": now.isoformat()})
    ledger.append(path, {"event": "reject", "ip": "203.0.113.7", "reason": "unknown-code", "ts": now.isoformat()})
    events = ledger.read_ask_events(path)
    assert [e["id"] for e in events] == ["elections-team"]   # rejects excluded


def test_counter_caps_per_identity(tmp_path):
    from corpus_server.gate.counts import Counter
    c = Counter({"standard": {"cap": 2}})
    c.seed([{"id": "x"}])                 # 1 already this window
    assert c.under_cap("x", "standard")   # 1 < 2
    c.increment("x")                      # now 2
    assert not c.under_cap("x", "standard")


def test_ratelimit_429_then_block(tmp_path):
    from corpus_server.gate.ratelimit import RateLimiter
    rl = RateLimiter(per_minute=2, block_after=2, block_for="15m")
    now = datetime(2026, 6, 16, 9, 0, 0, tzinfo=UTC)
    assert rl.check("1.1.1.1", now)[0] is True
    assert rl.check("1.1.1.1", now)[0] is True
    ok, retry = rl.check("1.1.1.1", now)   # third within the minute
    assert ok is False and retry > 0
    rl.record_401("2.2.2.2", now); rl.record_401("2.2.2.2", now)
    assert rl.check("2.2.2.2", now)[0] is False   # blocked after 2 × 401


def _decider(tmp_path, scheme="access-code"):
    from corpus_server.gate.config import load_gate_config
    from corpus_server.gate.counts import Counter
    from corpus_server.gate.ratelimit import RateLimiter
    cfg = load_gate_config(_gate_yaml(tmp_path, auth={"scheme": scheme} if scheme == "none"
                                      else {"scheme": "access-code", "access_list": str(_access_csv(tmp_path))}))
    return cfg, Counter(cfg["roles"]), RateLimiter(3, 2, "15m")


def test_decide_paths(tmp_path):
    from corpus_server.gate.decide import decide
    cfg, counter, limiter = _decider(tmp_path)
    al = Path(cfg["auth"]["access_list"])
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    common = dict(cfg=cfg, access_list_path=al, counter=counter, limiter=limiter,
                  ip="9.9.9.9", method="POST", now=now)
    # valid code, exposed ask → 200 + event
    d, ev = decide(uri="/ask/chat", authorization="Bearer a1b2c3", **common)
    assert d.status == 200 and ev["id"] == "elections-team" and ev["ask"] == "chat"
    # bad code → 401, no Retry-After
    d, ev = decide(uri="/ask/chat", authorization="Bearer nope", **common)
    assert d.status == 401 and d.body == {"error": "unauthorized"} and "Retry-After" not in d.headers and ev is None
    # unexposed ask → 403
    d, ev = decide(uri="/ask/secret", authorization="Bearer a1b2c3", **common)
    assert d.status == 403 and d.body == {"error": "ask_not_exposed"}


def test_decide_cap_429_has_no_retry_after(tmp_path):
    from corpus_server.gate.decide import decide
    cfg, counter, limiter = _decider(tmp_path)
    al = Path(cfg["auth"]["access_list"])
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    counter.seed([{"id": "elections-team"}, {"id": "elections-team"}])   # already at cap 2
    d, ev = decide(cfg=cfg, access_list_path=al, counter=counter, limiter=limiter,
                   ip="9.9.9.9", method="POST", uri="/ask/chat",
                   authorization="Bearer a1b2c3", now=now)
    assert d.status == 429 and d.body == {"error": "quota_exceeded"} and "Retry-After" not in d.headers


def test_decide_rate_limit_429_has_retry_after(tmp_path):
    from corpus_server.gate.config import load_gate_config
    from corpus_server.gate.counts import Counter
    from corpus_server.gate.decide import decide
    from corpus_server.gate.ratelimit import RateLimiter
    # cap=100 so quota never interferes; genuinely exercises the rate limiter
    cfg = load_gate_config(_gate_yaml(tmp_path,
        auth={"scheme": "access-code", "access_list": str(_access_csv(tmp_path))},
        roles={"standard": {"cap": 100}, "trial": {"cap": 100}}))
    counter = Counter(cfg["roles"])
    limiter = RateLimiter(per_minute=3, block_after=2, block_for="15m")
    al = Path(cfg["auth"]["access_list"])
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    call = lambda: decide(cfg=cfg, access_list_path=al, counter=counter, limiter=limiter,
                          ip="8.8.8.8", method="POST", uri="/ask/chat",
                          authorization="Bearer a1b2c3", now=now)
    for _ in range(3):
        call()                       # exhaust per_minute=3
    d, ev = call()
    assert d.status == 429 and d.body == {"error": "rate_limited"} and int(d.headers["Retry-After"]) > 0


# Fix 1: under access-code, no-auth probe of a non-ask path must return 401 (not 403)
def test_decide_no_auth_non_ask_returns_401(tmp_path):
    from corpus_server.gate.decide import decide
    cfg, counter, limiter = _decider(tmp_path)
    al = Path(cfg["auth"]["access_list"])
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    # GET /api/status is not an ask path; no Authorization header
    d, ev = decide(cfg=cfg, access_list_path=al, counter=counter, limiter=limiter,
                   ip="1.2.3.4", method="GET", uri="/api/status",
                   authorization=None, now=now)
    assert d.status == 401 and d.body == {"error": "unauthorized"} and ev is None


# Fix 1: confirm valid code + unexposed ask → 403 (not broken by reorder)
def test_decide_valid_code_unexposed_ask_returns_403(tmp_path):
    from corpus_server.gate.decide import decide
    cfg, counter, limiter = _decider(tmp_path)
    al = Path(cfg["auth"]["access_list"])
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    d, ev = decide(cfg=cfg, access_list_path=al, counter=counter, limiter=limiter,
                   ip="1.2.3.4", method="POST", uri="/ask/secret",
                   authorization="Bearer a1b2c3", now=now)
    assert d.status == 403 and d.body == {"error": "ask_not_exposed"} and ev is None


# Fix 1: bad code + ask path → 401 (not 403)
def test_decide_bad_code_ask_path_returns_401(tmp_path):
    from corpus_server.gate.decide import decide
    cfg, counter, limiter = _decider(tmp_path)
    al = Path(cfg["auth"]["access_list"])
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    d, ev = decide(cfg=cfg, access_list_path=al, counter=counter, limiter=limiter,
                   ip="1.2.3.4", method="POST", uri="/ask/chat",
                   authorization="Bearer badcode", now=now)
    assert d.status == 401 and d.body == {"error": "unauthorized"} and ev is None


# Fix 2: missing X-Forwarded-For → 400 with {"error": "missing_forwarded_for"}
def test_gate_app_missing_forwarded_for_returns_400(tmp_path):
    from fastapi.testclient import TestClient
    from corpus_server.gate.app import create_gate
    app = create_gate(_gate_yaml(tmp_path,
        auth={"scheme": "access-code", "access_list": str(_access_csv(tmp_path))}))
    client = TestClient(app)
    # No X-Forwarded-For header
    r = client.get("/", headers={
        "X-Forwarded-Method": "POST",
        "X-Forwarded-Uri": "/ask/chat",
        "Authorization": "Bearer a1b2c3",
    })
    assert r.status_code == 400 and r.json() == {"error": "missing_forwarded_for"}


def test_check_valid_code_204_no_event_no_cap(tmp_path):
    from corpus_server.gate.decide import decide
    cfg, counter, limiter = _decider(tmp_path)
    al = Path(cfg["auth"]["access_list"])
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    counter.seed([{"id": "elections-team"}, {"id": "elections-team"}])  # already AT cap 2
    d, ev = decide(cfg=cfg, access_list_path=al, counter=counter, limiter=limiter,
                   ip="9.9.9.9", method="POST", uri="/api/check",
                   authorization="Bearer a1b2c3", now=now)
    # currently-accepted: 200 even though over cap (check is not usage), no ask event
    assert d.status == 200 and d.body == {} and ev is None

def test_check_bad_code_401(tmp_path):
    from corpus_server.gate.decide import decide
    cfg, counter, limiter = _decider(tmp_path)
    al = Path(cfg["auth"]["access_list"])
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    d, ev = decide(cfg=cfg, access_list_path=al, counter=counter, limiter=limiter,
                   ip="9.9.9.9", method="POST", uri="/api/check",
                   authorization="Bearer nope", now=now)
    assert d.status == 401 and d.body == {"error": "unauthorized"} and ev is None

def test_check_rides_per_minute_limit(tmp_path):
    from corpus_server.gate.decide import decide
    cfg, counter, limiter = _decider(tmp_path)  # per_minute=3 from _gate_yaml
    al = Path(cfg["auth"]["access_list"])
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    common = dict(cfg=cfg, access_list_path=al, counter=counter, limiter=limiter,
                  ip="7.7.7.7", method="POST", uri="/api/check",
                  authorization="Bearer a1b2c3", now=now)
    for _ in range(3):
        d, _ev = decide(**common)
        assert d.status == 200
    d, _ev = decide(**common)   # 4th within the minute → throttled, same as ask
    assert d.status == 429 and d.body == {"error": "rate_limited"}


def test_gate_app_end_to_end(tmp_path):
    from fastapi.testclient import TestClient
    from corpus_server.gate.app import create_gate
    app = create_gate(_gate_yaml(tmp_path,
        auth={"scheme": "access-code", "access_list": str(_access_csv(tmp_path))}))
    client = TestClient(app)
    hdr = lambda code: {"X-Forwarded-Method": "POST", "X-Forwarded-Uri": "/ask/chat",
                        "X-Forwarded-For": "5.5.5.5", "Authorization": f"Bearer {code}"}
    assert client.get("/", headers=hdr("a1b2c3")).status_code == 200
    assert client.get("/", headers=hdr("nope")).status_code == 401
    # ledger recorded one ask + one reject for the current month
    from corpus_server.gate import ledger
    from datetime import datetime, timezone
    path = ledger.window_path(tmp_path / "ledger.jsonl", "month", datetime.now(timezone.utc))
    kinds = [json.loads(l)["event"] for l in path.read_text().splitlines()]
    assert "ask" in kinds and "reject" in kinds


def test_gate_app_missing_forwarded_method_returns_400(tmp_path):
    from fastapi.testclient import TestClient
    from corpus_server.gate.app import create_gate
    app = create_gate(_gate_yaml(tmp_path,
        auth={"scheme": "access-code", "access_list": str(_access_csv(tmp_path))}))
    r = TestClient(app).get("/", headers={
        "X-Forwarded-For": "5.5.5.5",
        "X-Forwarded-Uri": "/ask/chat",
        "Authorization": "Bearer a1b2c3",
    })
    assert r.status_code == 400 and r.json() == {"error": "missing_forwarded_method"}


def test_gate_app_missing_forwarded_uri_returns_400(tmp_path):
    from fastapi.testclient import TestClient
    from corpus_server.gate.app import create_gate
    app = create_gate(_gate_yaml(tmp_path,
        auth={"scheme": "access-code", "access_list": str(_access_csv(tmp_path))}))
    r = TestClient(app).get("/", headers={
        "X-Forwarded-For": "5.5.5.5",
        "X-Forwarded-Method": "POST",
        "Authorization": "Bearer a1b2c3",
    })
    assert r.status_code == 400 and r.json() == {"error": "missing_forwarded_uri"}
