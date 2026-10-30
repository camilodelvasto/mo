import asyncio
import json
import random
import shutil
import sqlite3
import string
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from shapes.sheets.src.fields import parse_fields
from shapes.sheets.src.rebuild import rebuild_state, _apply_op


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_ingest_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{ts}-{rand}"


def create_app(content_dir: Path, static_dir: Path | None = None) -> FastAPI:
    content_dir = Path(content_dir)
    sheet = yaml.safe_load((content_dir / "sheet.yaml").read_text())
    fields = parse_fields(sheet)
    field_names = {f.name for f in fields}
    field_type_map = {f.name: f for f in fields}
    rebuild_state(content_dir)

    pipeline_inputs = sheet.get("pipeline", {}).get("inputs", {})

    # Validate no key collisions across categories
    capability_keys = set((sheet.get("keys") or {}).values())
    pipeline_keys = {spec["key"] for spec in pipeline_inputs.values() if "key" in spec}
    field_keys = {f.key for f in fields if f.key}
    for key in pipeline_keys & capability_keys:
        raise ValueError(f"Key '{key}' declared in both pipeline.inputs and keys")
    for key in field_keys & capability_keys:
        raise ValueError(f"Key '{key}' declared in both fields and keys")
    for key in pipeline_keys & field_keys:
        raise ValueError(f"Key '{key}' declared in both pipeline.inputs and fields")

    # Kinds that go through inbox: everything except bypass_inference (SET)
    ingest_kinds = set()
    for kind, spec in pipeline_inputs.items():
        if not spec.get("bypass_inference"):
            ingest_kinds.add(kind)

    app = FastAPI()

    class HostHeaderMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            host = request.headers.get("host", "")
            hostname = host.split(":")[0]
            if hostname not in ("localhost", "127.0.0.1", "testserver"):
                return Response("Forbidden: invalid Host header", status_code=403)
            response = await call_next(request)
            # No cache for static files — ensures browser always gets latest JS/CSS
            if not request.url.path.startswith("/api/"):
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response

    app.add_middleware(HostHeaderMiddleware)

    sse_clients: list[asyncio.Queue] = []
    ops_version = 0

    async def _broadcast(event_type: str, data: dict | None = None):
        payload = json.dumps(data) if data else "{}"
        message = f"event: {event_type}\ndata: {payload}\n\n"
        dead = []
        for q in sse_clients:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            sse_clients.remove(q)

    def _serialize_fields(fields_list):
        return [
            {
                "name": f.name,
                "type": f.type,
                "label": f.label,
                "values": f.values,
                "align": f.align,
                "description": f.description,
                "action": f.action,
                "key": f.key,
            }
            for f in fields_list
        ]

    def _get_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(content_dir / "state.sqlite"))
        conn.row_factory = sqlite3.Row
        return conn

    def _validate_entry(entry: dict) -> None:
        op = entry.get("op")
        if op not in ("insert", "update"):
            raise HTTPException(400, f"Unknown op: {op}")
        if "id" not in entry:
            raise HTTPException(400, "Missing id")
        if "values" not in entry:
            raise HTTPException(400, "Missing values")
        if "ts" not in entry:
            raise HTTPException(400, "Missing ts")
        for key in entry["values"]:
            if key not in field_names:
                raise HTTPException(400, f"Unknown field: {key}")

    def _handle_append(entry: dict):
        if "id" not in entry:
            raise HTTPException(400, "Missing id")
        if "field" not in entry:
            raise HTTPException(400, "Missing field")
        if "entry" not in entry:
            raise HTTPException(400, "Missing entry")
        if "ts" not in entry:
            raise HTTPException(400, "Missing ts")

        field_name = entry["field"]
        field = field_type_map.get(field_name)
        if not field or field.type != "log":
            raise HTTPException(400, f"Field '{field_name}' is not a log field")

        ops_path = content_dir / "ops.jsonl"
        with open(ops_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        conn = _get_db()
        try:
            row = conn.execute("SELECT * FROM rows WHERE id = ?", (entry["id"],)).fetchone()
            if not row:
                raise HTTPException(404, f"Row not found: {entry['id']}")
            current = json.loads(row[field_name] or "[]")
            current.append(entry["entry"])
            updates = {field_name: json.dumps(current, ensure_ascii=False)}
            if "updated_at" in field_names:
                updates["updated_at"] = _now_iso()
            sets = ", ".join(f"{k} = ?" for k in updates)
            vals = list(updates.values()) + [entry["id"]]
            conn.execute(f"UPDATE rows SET {sets} WHERE id = ?", vals)
            conn.commit()
        finally:
            conn.close()

        return {"status": "ok", "op": "append", "id": entry["id"]}

    @app.get("/api/sheet")
    def get_sheet():
        return {
            "title": sheet.get("title", ""),
            "fields": _serialize_fields(fields),
            "pipeline": sheet.get("pipeline", {}),
            "keys": sheet.get("keys", {}),
            "view": sheet.get("view"),
            "ingest": sheet.get("ingest"),
        }

    @app.get("/api/tokens")
    def get_tokens():
        tokens = {}
        tokens_path = content_dir / "tokens.yaml"
        if tokens_path.exists():
            tokens.update(yaml.safe_load(tokens_path.read_text()) or {})
        sheet_tokens = sheet.get("tokens")
        if sheet_tokens:
            tokens.update(sheet_tokens)
        return tokens

    @app.get("/api/events")
    async def sse_events():
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        sse_clients.append(queue)

        async def event_stream():
            yield ": connected\n\n"
            ping_counter = 0
            try:
                while True:
                    try:
                        msg = queue.get_nowait()
                        yield msg
                        ping_counter = 0
                    except asyncio.QueueEmpty:
                        ping_counter += 1
                        if ping_counter >= 300:
                            yield ": ping\n\n"
                            ping_counter = 0
                        await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                pass
            finally:
                if queue in sse_clients:
                    sse_clients.remove(queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.post("/api/entries")
    async def post_entry(request: Request):
        nonlocal ops_version
        entry = await request.json()

        if entry.get("op") == "append":
            result = _handle_append(entry)
            ops_version += 1
            await _broadcast("rows", {"version": ops_version})
            return result

        now = _now_iso()
        if entry.get("op") == "insert" and "created_at" in field_names:
            entry.setdefault("values", {})
            entry["values"]["created_at"] = now
        if "updated_at" in field_names:
            entry.setdefault("values", {})
            entry["values"]["updated_at"] = now

        _validate_entry(entry)

        ops_path = content_dir / "ops.jsonl"
        with open(ops_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        conn = _get_db()
        try:
            _apply_op(conn, entry)
            conn.commit()
        finally:
            conn.close()

        ops_version += 1
        await _broadcast("rows", {"version": ops_version})
        return {"status": "ok", "op": entry["op"], "id": entry["id"]}

    @app.get("/api/rows")
    def get_rows():
        conn = _get_db()
        rows = [dict(r) for r in conn.execute("SELECT * FROM rows").fetchall()]
        conn.close()
        return rows

    @app.get("/api/rows/{row_id}")
    def get_row(row_id: str):
        conn = _get_db()
        row = conn.execute(
            "SELECT * FROM rows WHERE id = ?", (row_id,)
        ).fetchone()
        conn.close()
        if not row:
            raise HTTPException(404, f"Row not found: {row_id}")
        return dict(row)

    @app.post("/api/ingest", status_code=202)
    async def post_ingest(request: Request):
        body = await request.json()
        kind = body.get("kind")
        payload = body.get("payload", {})

        if not kind or kind not in ingest_kinds:
            allowed = ", ".join(sorted(ingest_kinds))
            raise HTTPException(400, f"Invalid kind: {kind}. Allowed: {allowed}")

        handler = pipeline_inputs[kind]
        handler_context = handler.get("context", {})

        context_parts = []
        if handler_context.get("row_id") == "required":
            row_id = payload.get("row_id")
            if not row_id:
                raise HTTPException(400, f"{kind} requires row_id in payload")
            context_parts.append(f"row_id={row_id}")

        header = kind
        if context_parts:
            header += " " + " ".join(context_parts)

        lines = [header]
        text = payload.get("text", "")
        url = payload.get("url", "")
        if url:
            lines.append(url)
        elif text:
            lines.append(text)

        file_content = "\n".join(lines) + "\n"

        ingest_id = _generate_ingest_id()
        filename = f"{ingest_id}.{kind}.txt"
        inbox = content_dir / "ingest" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        staging = content_dir / "ingest" / "staging"
        staging.mkdir(parents=True, exist_ok=True)

        tmp = staging / filename
        tmp.write_text(file_content)
        target = inbox / filename
        assert target.resolve().is_relative_to(inbox.resolve())
        shutil.move(str(tmp), str(target))

        return {"ingest_id": ingest_id}

    @app.get("/sync/status")
    async def sync_status():
        from cli.sync.client import SyncClient

        client = SyncClient()
        if not client.is_available():
            return {"state": "not synced"}
        try:
            await client.connect()
            all_status = await client.status()
            folder_name = content_dir.name
            folder_status = all_status.get(folder_name)
            if folder_status is None:
                return {"state": "not synced"}
            return folder_status
        except Exception:
            return {"state": "sync: offline"}
        finally:
            await client.close()

    if static_dir and static_dir.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
