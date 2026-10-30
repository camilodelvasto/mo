"""Tests verifying that API routes live under /api/ and old routes return 404."""
import yaml
from fastapi.testclient import TestClient

from shapes.sheets.src.api import create_app


def test_api_rows_returns_200(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/rows")
    assert response.status_code == 200


def test_api_entries_post_returns_200(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.post(
        "/api/entries",
        json={
            "op": "insert",
            "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {"name": "Apt A", "amount": 1200, "status": "new"},
        },
    )
    assert response.status_code == 200


def test_api_rows_by_id_returns_200(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    client.post(
        "/api/entries",
        json={
            "op": "insert",
            "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {"name": "Apt A", "amount": 1200, "status": "new"},
        },
    )
    response = client.get("/api/rows/r20260501100000")
    assert response.status_code == 200
    assert response.json()["name"] == "Apt A"


def test_old_entries_route_returns_404(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/entries",
        json={
            "op": "insert",
            "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {"name": "Apt A"},
        },
    )
    assert response.status_code == 404


def test_old_rows_route_returns_404(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/rows")
    assert response.status_code == 404


def test_old_rows_by_id_route_returns_404(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/rows/r20260501100000")
    assert response.status_code == 404


# --- Task 2: GET /api/sheet ---

def test_get_sheet_returns_fields(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/sheet")
    assert response.status_code == 200
    data = response.json()
    assert "fields" in data
    assert "pipeline" in data
    assert "title" in data
    assert data["title"] == "Test Sheet"
    names = [f["name"] for f in data["fields"]]
    assert "name" in names
    assert "status" in names
    name_field = next(f for f in data["fields"] if f["name"] == "name")
    assert name_field["type"] == "string"
    assert name_field["label"] == "Name"


def test_get_sheet_includes_enum_values(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/sheet")
    data = response.json()
    status_field = next(f for f in data["fields"] if f["name"] == "status")
    assert status_field["type"] == "enum"
    assert isinstance(status_field["values"], list)
    assert "new" in status_field["values"]
    assert "done" in status_field["values"]


def test_get_sheet_includes_pipeline_inputs(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/sheet")
    data = response.json()
    inputs = data["pipeline"]["inputs"]
    assert "NEW" in inputs
    assert "SET" in inputs
    assert "LOG" in inputs


# --- Task 3: GET /api/tokens ---

def test_get_tokens_empty_when_no_tokens_file(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/tokens")
    assert response.status_code == 200
    assert response.json() == {}


def test_get_tokens_from_tokens_yaml(sheet_dir):
    (sheet_dir / "tokens.yaml").write_text(
        yaml.dump({"primary": "#3b82f6", "danger": "#ef4444"})
    )
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/tokens")
    assert response.status_code == 200
    data = response.json()
    assert data["primary"] == "#3b82f6"
    assert data["danger"] == "#ef4444"


def test_get_tokens_from_sheet_yaml_tokens_block(sheet_dir):
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet["tokens"] = {"accent": "#8b5cf6"}
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/tokens")
    assert response.status_code == 200
    assert response.json()["accent"] == "#8b5cf6"


def test_get_tokens_sheet_yaml_overrides_tokens_yaml(sheet_dir):
    (sheet_dir / "tokens.yaml").write_text(yaml.dump({"primary": "#aabbcc"}))
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet["tokens"] = {"primary": "#ffffff"}
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/tokens")
    assert response.json()["primary"] == "#ffffff"


# --- Task 4: GET /api/events SSE ---

def test_sse_endpoint_returns_event_stream(sheet_dir):
    import socket
    import threading
    import time
    import uvicorn

    app = create_app(sheet_dir)

    # Find a free port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    # Wait until the server is ready
    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start in time"

    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/api/events")
    resp = conn.getresponse()
    status = resp.status
    ct = resp.headers.get("content-type", "")
    conn.close()
    server.should_exit = True

    assert status == 200
    assert "text/event-stream" in ct


# --- Task 5: Host header check middleware ---

def test_host_header_check_rejects_foreign_host(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/rows", headers={"Host": "evil.com"})
    assert response.status_code == 403


def test_host_header_check_allows_localhost(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/rows", headers={"Host": "localhost:4200"})
    assert response.status_code == 200


def test_host_header_check_allows_127(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/rows", headers={"Host": "127.0.0.1:4200"})
    assert response.status_code == 200


# --- Task 6: POST /api/ingest ---

def test_ingest_new_returns_202(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.post(
        "/api/ingest",
        json={"kind": "NEW", "payload": {"text": "2-Zimmer Vossstrasse 35"}},
    )
    assert response.status_code == 202
    assert "ingest_id" in response.json()


def test_ingest_creates_inbox_file(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    client.post(
        "/api/ingest",
        json={"kind": "NEW", "payload": {"text": "2-Zimmer Vossstrasse 35"}},
    )
    inbox = sheet_dir / "ingest" / "inbox"
    files = [f for f in inbox.iterdir() if f.is_file()]
    assert len(files) == 1
    content = files[0].read_text()
    assert content.startswith("NEW\n")
    assert "2-Zimmer Vossstrasse 35" in content


def test_ingest_update_includes_row_id(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    client.post(
        "/api/ingest",
        json={"kind": "UPDATE", "payload": {"row_id": "r20260501100000", "text": "sent application"}},
    )
    inbox = sheet_dir / "ingest" / "inbox"
    files = [f for f in inbox.iterdir() if f.is_file()]
    content = files[0].read_text()
    assert "UPDATE row_id=r20260501100000" in content


def test_ingest_rejects_unknown_kind(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.post(
        "/api/ingest",
        json={"kind": "DESTROY", "payload": {"text": "nope"}},
    )
    assert response.status_code == 400


def test_ingest_rejects_set_kind(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.post(
        "/api/ingest",
        json={"kind": "SET", "payload": {"text": "nope"}},
    )
    assert response.status_code == 400


def test_ingest_filename_is_server_controlled(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    client.post(
        "/api/ingest",
        json={"kind": "NEW", "payload": {"text": "../../../etc/passwd"}},
    )
    inbox = sheet_dir / "ingest" / "inbox"
    files = [f for f in inbox.iterdir() if f.is_file()]
    filename = files[0].name
    assert ".." not in filename
    assert "passwd" not in filename
    assert filename.endswith(".txt")
