import json
import sqlite3
from unittest.mock import AsyncMock, patch, MagicMock

from fastapi.testclient import TestClient

from shapes.sheets.src.api import create_app


def test_post_insert(sheet_dir):
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
    result = response.json()
    assert result["op"] == "insert"
    assert result["id"] == "r20260501100000"


def test_post_insert_persists_to_ops_jsonl(sheet_dir):
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
    ops = (sheet_dir / "ops.jsonl").read_text().strip().splitlines()
    assert len(ops) == 1
    op = json.loads(ops[0])
    assert op["op"] == "insert"
    assert op["id"] == "r20260501100000"


def test_get_rows_empty(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/rows")
    assert response.status_code == 200
    assert response.json() == []


def test_get_rows_after_insert(sheet_dir):
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
    response = client.get("/api/rows")
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Apt A"


def test_get_single_row(sheet_dir):
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


def test_get_row_not_found(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.get("/api/rows/nonexistent")
    assert response.status_code == 404


def test_post_rejects_unknown_field(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.post(
        "/api/entries",
        json={
            "op": "insert",
            "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {"nonexistent_field": "value"},
        },
    )
    assert response.status_code == 400


def test_post_rejects_unknown_op(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    response = client.post(
        "/api/entries",
        json={
            "op": "delete",
            "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {},
        },
    )
    assert response.status_code == 400


def test_post_insert_sets_created_at(sheet_dir):
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
    row = response.json()
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


def test_post_update_sets_updated_at(sheet_dir):
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
    r1 = client.get("/api/rows/r20260501100000").json()

    import time
    time.sleep(0.01)

    client.post(
        "/api/entries",
        json={
            "op": "update",
            "ts": "2026-05-01T14:00:00Z",
            "id": "r20260501100000",
            "values": {"status": "done"},
        },
    )
    r2 = client.get("/api/rows/r20260501100000").json()
    assert r2["updated_at"] is not None
    assert r2["created_at"] == r1["created_at"]


def test_post_insert_overwrites_explicit_created_at(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    client.post(
        "/api/entries",
        json={
            "op": "insert",
            "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {"name": "Apt A", "created_at": "1999-01-01T00:00:00Z"},
        },
    )
    row = client.get("/api/rows/r20260501100000").json()
    assert row["created_at"] != "1999-01-01T00:00:00Z"


def test_timestamps_only_injected_if_fields_declared(sheet_dir):
    """created_at/updated_at should only be injected if the schema declares them."""
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
    # The test fixture declares created_at and updated_at, so they should be there
    row = client.get("/api/rows/r20260501100000").json()
    assert row["created_at"] is not None


def test_post_update_modifies_row(sheet_dir):
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
    client.post(
        "/api/entries",
        json={
            "op": "update",
            "ts": "2026-05-01T14:00:00Z",
            "id": "r20260501100000",
            "values": {"status": "done"},
        },
    )
    response = client.get("/api/rows/r20260501100000")
    row = response.json()
    assert row["status"] == "done"
    assert row["name"] == "Apt A"


def test_post_append_to_log_field(sheet_dir):
    import yaml
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet["fields"]["activity"] = {"type": "log", "label": "Activity"}
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))

    app = create_app(sheet_dir)
    client = TestClient(app)
    client.post("/api/entries", json={
        "op": "insert", "ts": "2026-05-01T10:00:00Z", "id": "r20260501100000",
        "values": {"name": "Apt A", "amount": 1200, "status": "new"},
    })
    response = client.post("/api/entries", json={
        "op": "append", "ts": "2026-05-01T14:00:00Z", "id": "r20260501100000",
        "field": "activity",
        "entry": {"ts": "2026-05-01T14:00:00Z", "by": "alex", "text": "sent application"},
    })
    assert response.status_code == 200
    row = client.get("/api/rows/r20260501100000").json()
    activity = json.loads(row["activity"])
    assert len(activity) == 1
    assert activity[0]["text"] == "sent application"


def test_post_append_multiple_entries(sheet_dir):
    import yaml
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet["fields"]["activity"] = {"type": "log", "label": "Activity"}
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))

    app = create_app(sheet_dir)
    client = TestClient(app)
    client.post("/api/entries", json={
        "op": "insert", "ts": "2026-05-01T10:00:00Z", "id": "r20260501100000",
        "values": {"name": "Apt A"},
    })
    client.post("/api/entries", json={
        "op": "append", "ts": "2026-05-01T14:00:00Z", "id": "r20260501100000",
        "field": "activity",
        "entry": {"ts": "2026-05-01T14:00:00Z", "by": "alex", "text": "first"},
    })
    client.post("/api/entries", json={
        "op": "append", "ts": "2026-05-01T16:00:00Z", "id": "r20260501100000",
        "field": "activity",
        "entry": {"ts": "2026-05-01T16:00:00Z", "by": "a", "text": "second"},
    })
    row = client.get("/api/rows/r20260501100000").json()
    activity = json.loads(row["activity"])
    assert len(activity) == 2
    assert activity[0]["text"] == "first"
    assert activity[1]["text"] == "second"


def test_post_append_rejects_non_log_field(sheet_dir):
    app = create_app(sheet_dir)
    client = TestClient(app)
    client.post("/api/entries", json={
        "op": "insert", "ts": "2026-05-01T10:00:00Z", "id": "r20260501100000",
        "values": {"name": "Apt A"},
    })
    response = client.post("/api/entries", json={
        "op": "append", "ts": "2026-05-01T14:00:00Z", "id": "r20260501100000",
        "field": "name",
        "entry": {"ts": "2026-05-01T14:00:00Z", "by": "alex", "text": "test"},
    })
    assert response.status_code == 400


def test_sync_status_not_available(sheet_dir):
    """When sync daemon socket doesn't exist, returns not synced."""
    app = create_app(sheet_dir)
    client = TestClient(app)
    with patch("cli.sync.client.SyncClient") as MockClient:
        instance = MockClient.return_value
        instance.is_available.return_value = False
        instance.close = AsyncMock()
        response = client.get("/sync/status")
    assert response.status_code == 200
    assert response.json() == {"state": "not synced"}


def test_sync_status_available(sheet_dir):
    """When sync daemon reports status for the folder, returns it."""
    app = create_app(sheet_dir)
    client = TestClient(app)
    folder_name = sheet_dir.name
    with patch("cli.sync.client.SyncClient") as MockClient:
        instance = MockClient.return_value
        instance.is_available.return_value = True
        instance.connect = AsyncMock()
        instance.status = AsyncMock(return_value={
            folder_name: {"state": "synced", "head": "abc123"}
        })
        instance.close = AsyncMock()
        response = client.get("/sync/status")
    assert response.status_code == 200
    assert response.json() == {"state": "synced", "head": "abc123"}


def test_sync_status_folder_not_in_sync(sheet_dir):
    """When daemon is up but folder is not tracked, returns not synced."""
    app = create_app(sheet_dir)
    client = TestClient(app)
    with patch("cli.sync.client.SyncClient") as MockClient:
        instance = MockClient.return_value
        instance.is_available.return_value = True
        instance.connect = AsyncMock()
        instance.status = AsyncMock(return_value={
            "other-folder": {"state": "synced", "head": "def456"}
        })
        instance.close = AsyncMock()
        response = client.get("/sync/status")
    assert response.status_code == 200
    assert response.json() == {"state": "not synced"}


def test_sync_status_daemon_error(sheet_dir):
    """When daemon connection fails, returns offline."""
    app = create_app(sheet_dir)
    client = TestClient(app)
    with patch("cli.sync.client.SyncClient") as MockClient:
        instance = MockClient.return_value
        instance.is_available.return_value = True
        instance.connect = AsyncMock(side_effect=ConnectionRefusedError)
        instance.close = AsyncMock()
        response = client.get("/sync/status")
    assert response.status_code == 200
    assert response.json() == {"state": "sync: offline"}
