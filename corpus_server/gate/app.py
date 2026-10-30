# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The forward-auth service Caddy consults. Reads the original request from
Caddy's X-Forwarded-Method / -Uri / -For headers, runs the decision, appends the
ledger event, and returns a status + small JSON body Caddy copies to the client.
Imports no engine code — it reaches the engine only over HTTP, via Caddy."""
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from corpus_server.gate import config, ledger
from corpus_server.gate.counts import Counter
from corpus_server.gate.decide import decide
from corpus_server.gate.ratelimit import RateLimiter


def create_gate(gate_yaml: Path) -> FastAPI:
    cfg = config.load_gate_config(gate_yaml)
    base = Path(cfg["ledger"])
    window = cfg["window"]
    access_list = (Path(cfg["auth"]["access_list"])
                   if cfg["auth"]["scheme"] == "access-code" else None)
    rl = cfg["rate_limit"]
    limiter = RateLimiter(rl["per_minute"], rl["block_after"], rl["block_for"])

    app = FastAPI()
    app.state.cfg = cfg
    app.state.window_key = None
    app.state.counter = Counter(cfg["roles"])

    def counter_for(now: datetime) -> Counter:
        # check-then-set is safe: synchronous within a single event-loop coroutine, no await, no lock needed
        key = ledger.window_suffix(window, now)
        if key != app.state.window_key:                 # boot, or window rolled
            app.state.window_key = key
            app.state.counter = Counter(cfg["roles"])
            app.state.counter.seed(
                ledger.read_ask_events(ledger.window_path(base, window, now)))
        return app.state.counter

    @app.api_route("/{path:path}",
                   methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    async def gate(request: Request, path: str):
        now = datetime.now(timezone.utc)
        h = request.headers
        xff = h.get("x-forwarded-for", "").split(",")[0].strip()
        if not xff:
            return JSONResponse(status_code=400, content={"error": "missing_forwarded_for"})
        ip = xff
        method = h.get("x-forwarded-method")
        if not method:
            return JSONResponse(status_code=400, content={"error": "missing_forwarded_method"})
        uri = h.get("x-forwarded-uri")
        if not uri:
            return JSONResponse(status_code=400, content={"error": "missing_forwarded_uri"})
        d, event = decide(cfg=cfg, access_list_path=access_list,
                          counter=counter_for(now), limiter=limiter,
                          ip=ip, method=method, uri=uri,
                          authorization=h.get("authorization"), now=now)
        path_w = ledger.window_path(base, window, now)
        if event is not None:
            ledger.append(path_w, event)
        elif d.status in (401, 403, 429):
            ledger.append(path_w, {"event": "reject", "ip": ip,
                                   "reason": d.body.get("error"), "ts": now.isoformat()})
        return JSONResponse(status_code=d.status, content=d.body, headers=d.headers)

    return app


_gate_config_env = os.environ.get("GATE_CONFIG")
if _gate_config_env is not None:
    app = create_gate(Path(_gate_config_env))
