import json
import threading
import time

import requests
import uvicorn
from unittest.mock import patch

from shapes.sheets.src.api import create_app
from shapes.sheets.src.processor import process_file
from shapes.sheets.src.types import InferenceResult
from shapes.sheets.src.watcher import detect_inbox_files


def _find_free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_full_pipeline_new_entry(sheet_dir):
    """Start API, drop a NEW file, process it, verify the row appears."""
    port = _find_free_port()
    api_url = f"http://127.0.0.1:{port}"

    app = create_app(sheet_dir)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            requests.get(f"{api_url}/api/rows", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.1)

    inbox = sheet_dir / "ingest" / "inbox"
    inbox_file = inbox / "test-entry.txt"
    inbox_file.write_text("NEW\nApt at Vossstrasse 35, 1200 EUR, 2 rooms")

    mock_result = InferenceResult(
        data={"name": "Vossstrasse 35", "amount": 1200.0, "status": "new"},
        backend="ollama", model="qwen3:8b", latency_ms=500, error=None,
        raw_response='{"name": "Vossstrasse 35", "amount": 1200.0, "status": "new"}',
    )

    with patch("shapes.sheets.src.processor._call_inference", return_value=mock_result):
        process_file(inbox_file, sheet_dir, api_url=api_url)

    resp = requests.get(f"{api_url}/api/rows")
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Vossstrasse 35"
    assert rows[0]["amount"] == 1200.0
    assert rows[0]["status"] == "new"

    ops = (sheet_dir / "ops.jsonl").read_text().strip().splitlines()
    assert len(ops) == 1
    op = json.loads(ops[0])
    assert op["op"] == "insert"

    journal = (sheet_dir / "ingest" / "journal.jsonl").read_text().strip().splitlines()
    assert len(journal) == 1
    entry = json.loads(journal[0])
    assert entry["kind"] == "NEW"
    assert entry["backend"] == "ollama"

    assert not inbox_file.exists()
    server.should_exit = True


def test_full_pipeline_update_entry(sheet_dir):
    """Insert a row, then update it, verify fields change."""
    port = _find_free_port()
    api_url = f"http://127.0.0.1:{port}"

    app = create_app(sheet_dir)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            requests.get(f"{api_url}/api/rows", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.1)

    requests.post(
        f"{api_url}/api/entries",
        json={
            "op": "insert", "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {"name": "Apt A", "amount": 1200, "status": "new"},
        },
    )

    inbox = sheet_dir / "ingest" / "inbox"
    update_file = inbox / "test-update.txt"
    update_file.write_text("UPDATE row_id=r20260501100000\n@a sent application at 14:00")

    mock_result = InferenceResult(
        data={"status": "done", "notes": "Applied at 14:00"},
        backend="ollama", model="qwen3:8b", latency_ms=300, error=None,
        raw_response='{"status": "done", "notes": "Applied at 14:00"}',
    )

    with patch("shapes.sheets.src.processor._call_inference", return_value=mock_result), \
         patch("shapes.sheets.src.processor._get_row_from_api", return_value={"id": "r20260501100000", "name": "Apt A", "amount": 1200, "status": "new"}):
        process_file(update_file, sheet_dir, api_url=api_url)

    resp = requests.get(f"{api_url}/api/rows/r20260501100000")
    row = resp.json()
    assert row["status"] == "done"
    assert row["notes"] == "Applied at 14:00"
    assert row["name"] == "Apt A"

    server.should_exit = True


def test_full_pipeline_set_bypass(sheet_dir):
    """SET bypasses inference entirely."""
    port = _find_free_port()
    api_url = f"http://127.0.0.1:{port}"

    app = create_app(sheet_dir)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            requests.get(f"{api_url}/api/rows", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.1)

    requests.post(
        f"{api_url}/api/entries",
        json={
            "op": "insert", "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {"name": "Apt A", "amount": 1200, "status": "new"},
        },
    )

    inbox = sheet_dir / "ingest" / "inbox"
    set_file = inbox / "test-set.txt"
    set_file.write_text("SET row_id=r20260501100000\namount = 1500")

    process_file(set_file, sheet_dir, api_url=api_url)

    resp = requests.get(f"{api_url}/api/rows/r20260501100000")
    row = resp.json()
    assert row["amount"] == 1500.0
    assert row["name"] == "Apt A"

    server.should_exit = True
