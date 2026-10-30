# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The localhost HTTP surface over one corpus. Routes map 1:1 to the endpoint
table. Reads come from the cache (catalogue, status) or a live fold of the one
sidecar (/doc/*). The service NEVER writes a sidecar — its only writes are
assert/order files into inbox/ (added in a later task). Binds localhost only."""
import asyncio
import json
import os
import select
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from ulid import ULID

from shapes.corpus.access import askfile, search as access_search, verify_media
from shapes.corpus.access.attest import AttestError
from shapes.corpus.access.errors import AttachmentError
from shapes.corpus.engine import identity, sidecar
from shapes.corpus.engine.errors import CapabilityError
from shapes.corpus.service import locks, payloads
from shapes.corpus.service.cache import Cache, _declared_fields, _field_specs


class AssertBody(BaseModel):
    doc_id: str
    fields: dict


class OrderBody(BaseModel):
    doc_id: str
    action: str
    # 'from' is a Python keyword; accept the JSON key "from" via the alias.
    from_: str | None = Field(default=None, alias="from")

    model_config = {"populate_by_name": True}


class Attachment(BaseModel):
    data: str
    signature: str
    media_type: str


class Turn(BaseModel):
    role: str
    content: str
    attachments: list[Attachment] = []


class AskBody(BaseModel):
    question: str
    history: list[Turn] = []
    attachments: list[Attachment] = []


# The wire kind → HTTP status table. The keys must match what the CLI's error_kind
# emits; any kind not listed (e.g. engine_error) is the 500 default. Module-level so
# both sides of the contract can be tested against one source.
_ASK_STATUS = {"unknown_ask": 404, "citation_check": 422, "synthesis_failed": 502}

_VERIFY_STATUS = {"too_large": 413, "wrong_type": 415, "undecodable": 422,
                  "no_attachments_policy": 409, "length_required": 411}


class _BodyClosingStream(StreamingResponse):
    """A StreamingResponse that closes its sync body when it is done, however it ends.
    Starlette never closes an abandoned sync body: on a client disconnect it cancels the
    send loop and leaves the generator suspended until the cyclic GC finds it, which an
    idle server may never run. The body's close() runs its own finally — for /ask that
    kills `mo corpus ask` and unlinks the temp files. Closing a body that never started
    is a no-op; it acquired nothing."""

    def __init__(self, body, **kw):
        super().__init__(body, **kw)
        self._body = body

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._body.close()


def _check_declared_length(headers, policy: dict) -> None:
    """The request's declared body length against the ask's declared bound — BEFORE
    the body is buffered. /verify is unmetered, so buffering first would let one
    request take the box's memory. No declared length → refused (never guessed)."""
    raw = headers.get("content-length")
    if raw is None:
        raise AttachmentError("length_required", "verify needs a Content-Length; chunked uploads are not accepted")
    try:
        declared = int(raw)
    except ValueError:
        raise AttachmentError("length_required", f"Content-Length {raw!r} is not an integer")
    if "max_bytes" in policy and declared > policy["max_bytes"]:
        raise AttachmentError("too_large",
            f"attachment declares {declared} bytes; the ask allows at most {policy['max_bytes']}")


def _ask_policy(corpus_dir: Path, name: str) -> dict | None:
    """The ask's declared attachments policy, or None. Unknown ask → HTTP 404."""
    from shapes.corpus.access.errors import AskError
    asks = askfile.load_asks(corpus_dir)
    try:
        ask = askfile.resolve_ask(asks, name)
    except AskError:
        raise HTTPException(404, f"no ask {name!r}")
    return ask.get("attachments")


def parse_where(raw: str | None) -> dict:
    """The single filter vocabulary, shared by /catalogue, /search and the CLI:
    space-separated key=value, conjunction only. No query language until a
    corpus needs disjunction."""
    where: dict = {}
    if not raw:
        return where
    for token in raw.split():
        if "=" not in token:
            raise HTTPException(400, f"bad where term {token!r}: expected key=value")
        key, value = token.split("=", 1)
        where[key] = value
    return where


def create_not_ready_app(reason: str, allow_origins: list | None = None) -> FastAPI:
    """The serve's holding surface when no corpus is mounted yet (cold box, not
    synced). It keeps the process UP (so the container is execable for `mo sync`'s
    verify_passport) and answers 503 on every ask, so the healthcheck reports
    unhealthy WITHOUT the process exiting. A deployed-but-unsynced box is a legible
    running state, not a crash."""
    app = FastAPI()
    if allow_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=allow_origins,
                           allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.post("/ask/{name}")
    def _not_ready(name: str):
        raise HTTPException(503, f"corpus not ready: {reason} — sync a corpus to this box")

    @app.get("/health")
    def _health():
        # The holding surface is deliberately NOT healthy: a deployed-but-unsynced
        # box has no corpus to answer from. 503 here keeps the container unhealthy
        # until a corpus is mounted (then create_app's /health takes over with 200).
        raise HTTPException(503, f"corpus not ready: {reason}")
    return app


def create_app(corpus_dir: Path, machine_root: Path | None = None,
               allow_origins: list | None = None) -> FastAPI:
    corpus = yaml.safe_load((corpus_dir / "corpus.yaml").read_text())
    flow = yaml.safe_load((corpus_dir / corpus["flow"].removeprefix("./")).read_text())
    declared = set(_declared_fields(flow))
    cache = Cache(corpus_dir, flow)
    cache.reconcile()

    app = FastAPI()
    if allow_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=allow_origins,
                           allow_methods=["GET", "POST"], allow_headers=["*"])
    app.state.cache = cache
    app.state.corpus_dir = corpus_dir.resolve()
    app.state.machine_root = machine_root
    app.state.verify_slots = None      # (BoundedSemaphore, bound), made on first /verify
    app.state.flow = flow

    app.state.subscribers = set()      # set[asyncio.Queue], one per /events listener

    def poll_once():
        for change in cache.tick():
            for q in list(app.state.subscribers):
                q.put_nowait(change)
    app.state.poll_once = poll_once

    @app.on_event("startup")
    async def _start_poller():
        async def loop():
            while True:
                await asyncio.sleep(1)
                poll_once()
        app.state._poller = asyncio.create_task(loop())

    def _pair_for(doc_id: str) -> Path:
        meta = identity.find_pair(corpus_dir, doc_id)
        if meta is None:
            raise HTTPException(404, f"no document {doc_id}")
        return meta.parent

    @app.get("/status")
    def status():
        return {"counts": cache.lens_counts(),
                "engine": locks.alive(locks.lock_path(corpus_dir, "engine.lock")),
                "service": locks.alive(locks.lock_path(corpus_dir, "service.lock"))}

    @app.get("/health")
    def health():
        """serve's own liveness contract — the deploy/healthcheck reads THIS, not a
        named ask. 200 means a corpus is loaded and serve is answering. Decoupled
        from ask.yaml on purpose: the embedder binding (local.embed) is verified by
        `mo sync`'s passport in this container BEFORE the flip, so health need not
        re-probe a user ask. The holding app (create_not_ready_app) returns 503."""
        return {"status": "ok"}

    @app.get("/catalogue")
    def catalogue(lens: str = "all", where: str | None = None,
                  field: str | None = None, value: str | None = None,
                  cursor: int = 0, limit: int = 100):
        w = parse_where(where)
        if field is not None and value is not None:
            w[field] = value
        return cache.catalogue(lens=lens, where=w, cursor=cursor, limit=limit)

    @app.get("/catalogue/counts")
    def catalogue_counts():
        return cache.lens_counts()

    @app.get("/facets")
    def facets():
        return cache.facets()

    @app.get("/fields")
    def fields():
        return {"fields": _field_specs(flow)}

    @app.get("/catalogue/{doc_id}")
    def catalogue_row(doc_id: str):
        row = cache.row(doc_id)
        if row is None:
            raise HTTPException(404, f"no cached row for {doc_id}")
        return row

    @app.get("/search")
    def search(q: str = ""):
        """Content search: reconcile the index, lexical-retrieve, roll up to docs.
        The catalogue merges these doc_ids with its instant metadata filter."""
        if not q.strip():
            return {"hits": []}
        if app.state.machine_root is None:
            raise HTTPException(500, "search unavailable: machine_root not set")
        hits = access_search.search_docs(app.state.corpus_dir, app.state.machine_root, q)
        return {"hits": hits}

    @app.get("/doc/{doc_id}")
    def doc(doc_id: str):
        pair = _pair_for(doc_id)
        return payloads.build_doc(sidecar.read(pair / "meta.yaml"), declared)

    @app.get("/doc/{doc_id}/custody")
    def custody(doc_id: str):
        pair = _pair_for(doc_id)
        return payloads.build_custody(sidecar.read(pair / "meta.yaml"), pair)

    @app.get("/doc/{doc_id}/log")
    def log(doc_id: str):
        pair = _pair_for(doc_id)
        return payloads.build_log(sidecar.read(pair / "meta.yaml"))

    @app.get("/doc/{doc_id}/chunks")
    def chunks(doc_id: str):
        return payloads.build_chunks(_pair_for(doc_id))

    def _artifact_file(doc_id: str, name: str) -> Path:
        """Resolve an artifact to its on-disk file, confined to its own bundle.
        Defence in depth: a manifest path must resolve inside its own pair — never
        let a crafted ./../ escape, even though the engine is the only writer."""
        pair = _pair_for(doc_id)
        doc = sidecar.read(pair / "meta.yaml")
        info = (doc.get("artifacts") or {}).get(name)
        if not info or "path" not in info:
            raise HTTPException(404, f"no artifact {name} for {doc_id}")
        path = info["path"]
        if not path.startswith("./"):
            raise HTTPException(409, f"artifact {name} is dispatched off-tree: {path}")
        f = pair / path[2:]
        if not f.resolve().is_relative_to(pair.resolve()):
            raise HTTPException(409, f"artifact {name} resolves outside the bundle")
        if not f.is_file():
            raise HTTPException(404, f"artifact {name} bytes are gone (custody-only)")
        return f

    @app.get("/doc/{doc_id}/artifacts/{name}")
    def artifact(doc_id: str, name: str):
        return FileResponse(_artifact_file(doc_id, name))

    @app.get("/doc/{doc_id}/path")
    def doc_path(doc_id: str, artifact: str = "original"):
        """The artifact's absolute filesystem path — so an operator can reveal it
        in the OS file manager. Meaningful only when the service runs on the same
        machine as the renderer (embed/local); resolution and bundle-confinement
        mirror /artifacts. 404 when the bytes are gone (custody-only)."""
        return {"path": str(_artifact_file(doc_id, artifact).resolve())}

    @app.get("/events")
    async def events():
        q: asyncio.Queue = asyncio.Queue()
        app.state.subscribers.add(q)

        async def gen():
            try:
                while True:
                    change = await q.get()
                    yield f"data: {json.dumps(change)}\n\n"
            finally:
                app.state.subscribers.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    inbox = corpus_dir / "inbox"

    @app.post("/assert")
    def post_assert(body: AssertBody):
        inbox.mkdir(parents=True, exist_ok=True)
        name = f"{ULID()}-{body.doc_id}.assert.yaml"
        payload = {"doc_id": body.doc_id, "by": "operator", "via": "service",
                   "fields": body.fields}
        (inbox / name).write_text(yaml.safe_dump(payload, sort_keys=False))
        return {"inbox": name}

    @app.post("/order")
    def post_order(body: OrderBody):
        inbox.mkdir(parents=True, exist_ok=True)
        name = f"{ULID()}-{body.doc_id}.order.yaml"
        payload = {"doc_id": body.doc_id, "by": "operator", "action": body.action}
        if body.from_ is not None:
            payload["from"] = body.from_
        (inbox / name).write_text(yaml.safe_dump(payload, sort_keys=False))
        return {"inbox": name}

    @app.get("/ask/{name}/policy")
    def ask_policy(name: str):
        return {"attachments": _ask_policy(app.state.corpus_dir, name)}

    @app.post("/verify/{name}")
    async def verify(name: str, request: Request):
        if app.state.machine_root is None:
            raise HTTPException(500, "verify unavailable: machine_root not set")
        policy = _ask_policy(app.state.corpus_dir, name)
        if policy is None:
            raise HTTPException(409, f"ask {name!r} does not accept attachments")
        try:
            _check_declared_length(request.headers, policy)
        except AttachmentError as exc:
            raise HTTPException(_VERIFY_STATUS[exc.kind], str(exc))
        # The body is bounded by the declared length above; reading it takes no slot, so
        # a slow upload never holds a decode slot for the whole transfer.
        raw = await request.body()
        declared_type = request.headers.get("content-type")
        if not declared_type:                     # no declared type is not a type
            raise HTTPException(400, "verify needs a Content-Type naming the upload's media type")
        # At most the binding's declared number of decodes at once (~300 MB each); past
        # it /verify REFUSES at once, never queues on the threadpool every sync handler
        # shares. No await between the check and the set: one loop, no race.
        if app.state.verify_slots is None:
            try:
                bound = verify_media.media_binding(app.state.machine_root)["concurrency"]
            except CapabilityError as exc:
                raise HTTPException(500, f"verify unavailable: {exc}")
            app.state.verify_slots = (threading.BoundedSemaphore(bound), bound)
        slots, bound = app.state.verify_slots
        if not slots.acquire(blocking=False):
            raise HTTPException(503, f"verify at capacity: {bound} in flight")
        try:
            # The decode + re-encode is CPU-bound and can take seconds: it runs in the
            # threadpool, never on the loop that serves every live stream.
            return await run_in_threadpool(verify_media.verify_and_sign,
                app.state.machine_root, name, policy, raw, declared_type)
        except AttachmentError as exc:
            raise HTTPException(_VERIFY_STATUS[exc.kind], str(exc))
        except (CapabilityError, AttestError) as exc:
            raise HTTPException(500, f"verify unavailable: {exc}")
        finally:
            slots.release()

    @app.post("/ask/{name}")
    def ask(name: str, body: AskBody, request: Request):
        """Shell `mo corpus ask … --json` — the CLI is the seam; the serve never
        re-implements engine logic. Relay the record, or map a typed engine error
        envelope to its status. A citation refusal is 422 (deterministic, do not
        auto-retry); a synthesis failure is 502; anything unmapped is 500."""
        mo = shutil.which("mo")
        if mo is None:
            raise HTTPException(502, "`mo` is not on PATH; install the CLI with `pip install -e .`")
        history = [t.model_dump() for t in body.history]
        wants_stream = "application/x-ndjson" in request.headers.get("accept", "")
        if wants_stream:
            import tempfile as _tempfile
            atts = [a.model_dump() for a in body.attachments]

            def _relay():
                # Everything this stream holds — the temp files (base64 images) and the
                # subprocess — is acquired HERE, inside the finally that releases it. A
                # response the client never reads acquires nothing; nothing can leak.
                tmp_paths, proc = [], None

                def _tmp(obj):
                    fd, path = _tempfile.mkstemp(suffix=".json", prefix="ask-")
                    tmp_paths.append(path)
                    with os.fdopen(fd, "w") as fh:
                        json.dump(obj, fh, ensure_ascii=False)
                    return path

                try:
                    # history/attachments can carry base64 images → pass via @file, never argv.
                    cmd = [mo, "corpus", "ask", str(app.state.corpus_dir), name, body.question,
                           "--stream", "--history", f"@{_tmp(history)}"]
                    if atts:
                        cmd += ["--attachments", f"@{_tmp(atts)}"]
                    try:
                        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    except OSError as exc:
                        # The 200 is already on the wire; the error event is the error channel.
                        yield json.dumps({"event": "error", "kind": "ask_failed",
                                          "detail": str(exc)}, ensure_ascii=False).encode() + b"\n"
                        return
                    yield from _relay_proc(proc)
                finally:
                    if proc is not None and proc.poll() is None:
                        proc.kill()                        # client went away, or we stopped early
                        try:
                            proc.wait(timeout=5)           # reap it; a killed ask is no zombie
                        except subprocess.TimeoutExpired:
                            # The 200 is already on the wire; nowhere to raise to. Say it.
                            print(f"ask stream: killed `mo corpus ask` (pid {proc.pid}) "
                                  f"did not exit within 5s", file=sys.stderr)
                    for p in tmp_paths:
                        try:
                            os.unlink(p)
                        except FileNotFoundError:
                            pass

            def _relay_proc(proc):
                # A stalled `mo corpus ask` would hang the browser forever, and a long silent
                # RAG gap can be idle-dropped by an intermediary. So: poll stdout; emit a
                # keepalive `ping` on idle; hard-stop a runaway subprocess with a clean error
                # event. The client ignores {"event":"ping"} and treats only done/error as
                # terminal, so neither the ping nor the timeout can be mistaken for an answer.
                HARD_TIMEOUT_S = 180     # a normal answer finishes well under 60s
                IDLE_PING_S = 10         # keepalive cadence during a silent RAG gap
                start = time.monotonic()
                fd = proc.stdout.fileno()
                buf = b""
                last_error = None   # errors ride stdout as events; the box log must not lose them
                while True:
                    if time.monotonic() - start > HARD_TIMEOUT_S:
                        proc.kill()
                        yield b'{"event": "error", "kind": "synthesis_failed", "detail": "ask timed out"}\n'
                        return
                    ready, _, _ = select.select([fd], [], [], IDLE_PING_S)
                    if not ready:
                        yield b'{"event": "ping"}\n'      # keepalive; the client ignores it
                        continue
                    chunk = os.read(fd, 65536)
                    if not chunk:                          # EOF: subprocess finished
                        if buf:
                            yield buf
                        break
                    buf += chunk
                    nl = buf.rfind(b"\n")
                    if nl >= 0:                            # flush all complete lines now
                        out, buf = buf[:nl + 1], buf[nl + 1:]
                        for line in out.splitlines():
                            if b'"error"' in line:         # cheap sieve; parsed only on exit
                                last_error = line
                        yield out
                # The 200 is already on the wire; a crashed subprocess must not
                # close the stream silently (the client would invent its own
                # story). The error event IS the error channel here.
                try:
                    rc = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill(); rc = -1
                if rc != 0:
                    err = proc.stderr.read().decode(errors="replace").strip()
                    detail = None
                    if last_error is not None:
                        try:
                            ev = json.loads(last_error)
                            if isinstance(ev, dict) and ev.get("event") == "error":
                                detail = ev.get("detail")
                        except ValueError:
                            pass
                    print(f"ask stream exited {rc}: {err or detail or ''}", file=sys.stderr)
                    reason = (err.splitlines()[-1] if err
                              else detail or f"ask exited {rc}")
                    yield json.dumps({"event": "error", "kind": "ask_failed",
                                      "detail": reason}, ensure_ascii=False).encode() + b"\n"

            return _BodyClosingStream(_relay(), media_type="application/x-ndjson")
        # ---- blocking (JSON) path ----
        # It puts history on argv, which base64 images overflow, and `mo corpus ask`
        # accepts attachments only on the streaming path. So the limit is stated, not
        # worked around by dropping what the caller sent.
        if body.attachments or any(t.attachments for t in body.history):
            raise HTTPException(406, "attachments need the streaming response: send "
                                     "Accept: application/x-ndjson")
        cmd = [mo, "corpus", "ask", str(app.state.corpus_dir), name, body.question,
               "--json", "--history", json.dumps(history, ensure_ascii=False)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=600)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "ask timed out")
        out = proc.stdout.decode().strip()
        if not out:
            raise HTTPException(502, proc.stderr.decode(errors="replace").strip()
                                or "ask produced no output")
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            raise HTTPException(502, f"ask returned non-JSON: {out[:200]}")
        if "error" in payload:
            status = _ASK_STATUS.get(payload["error"]["kind"], 500)
            return JSONResponse(status_code=status, content={"error": payload["error"]})
        return payload

    return app
