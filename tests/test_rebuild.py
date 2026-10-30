import json
import sqlite3

from shapes.sheets.src.rebuild import rebuild_state


def test_rebuild_empty_ops(sheet_dir):
    rebuild_state(sheet_dir)
    db = sqlite3.connect(str(sheet_dir / "state.sqlite"))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM rows").fetchall()
    db.close()
    assert rows == []


def test_rebuild_insert(sheet_dir):
    ops = [
        {
            "op": "insert",
            "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {"name": "Apt A", "amount": 1200, "status": "new"},
        }
    ]
    (sheet_dir / "ops.jsonl").write_text(
        "\n".join(json.dumps(o) for o in ops) + "\n"
    )
    rebuild_state(sheet_dir)
    db = sqlite3.connect(str(sheet_dir / "state.sqlite"))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM rows").fetchall()
    db.close()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["id"] == "r20260501100000"
    assert row["name"] == "Apt A"
    assert row["amount"] == 1200
    assert row["status"] == "new"


def test_rebuild_insert_then_update(sheet_dir):
    ops = [
        {
            "op": "insert",
            "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {"name": "Apt A", "amount": 1200, "status": "new"},
        },
        {
            "op": "update",
            "ts": "2026-05-01T14:00:00Z",
            "id": "r20260501100000",
            "values": {"status": "done", "notes": "Applied"},
        },
    ]
    (sheet_dir / "ops.jsonl").write_text(
        "\n".join(json.dumps(o) for o in ops) + "\n"
    )
    rebuild_state(sheet_dir)
    db = sqlite3.connect(str(sheet_dir / "state.sqlite"))
    db.row_factory = sqlite3.Row
    row = dict(db.execute("SELECT * FROM rows WHERE id = ?", ("r20260501100000",)).fetchone())
    db.close()
    assert row["status"] == "done"
    assert row["notes"] == "Applied"
    assert row["name"] == "Apt A"


def test_rebuild_with_log_field(sheet_dir):
    """Log fields store as TEXT in sqlite."""
    import yaml
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet["fields"]["activity"] = {"type": "log", "label": "Activity"}
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))

    rebuild_state(sheet_dir)
    db = sqlite3.connect(str(sheet_dir / "state.sqlite"))
    db.row_factory = sqlite3.Row
    cols = [row[1] for row in db.execute("PRAGMA table_info(rows)").fetchall()]
    db.close()
    assert "activity" in cols


def test_rebuild_append_op(sheet_dir):
    """Append op adds an entry to a log field's JSON array."""
    import yaml
    sheet = yaml.safe_load((sheet_dir / "sheet.yaml").read_text())
    sheet["fields"]["activity"] = {"type": "log", "label": "Activity"}
    (sheet_dir / "sheet.yaml").write_text(yaml.dump(sheet, sort_keys=False))

    ops = [
        {"op": "insert", "ts": "2026-05-01T10:00:00Z", "id": "r20260501100000",
         "values": {"name": "Apt A", "amount": 1200, "status": "new"}},
        {"op": "append", "ts": "2026-05-01T14:00:00Z", "id": "r20260501100000",
         "field": "activity",
         "entry": {"ts": "2026-05-01T14:00:00Z", "by": "alex", "text": "sent application"}},
        {"op": "append", "ts": "2026-05-01T16:00:00Z", "id": "r20260501100000",
         "field": "activity",
         "entry": {"ts": "2026-05-01T16:00:00Z", "by": "a", "text": "got viewing invite"}},
    ]
    (sheet_dir / "ops.jsonl").write_text("\n".join(json.dumps(o) for o in ops) + "\n")

    rebuild_state(sheet_dir)
    db = sqlite3.connect(str(sheet_dir / "state.sqlite"))
    db.row_factory = sqlite3.Row
    row = dict(db.execute("SELECT * FROM rows WHERE id = ?", ("r20260501100000",)).fetchone())
    db.close()

    activity = json.loads(row["activity"])
    assert len(activity) == 2
    assert activity[0]["by"] == "alex"
    assert activity[1]["text"] == "got viewing invite"


def test_rebuild_replaces_existing_db(sheet_dir):
    ops = [
        {
            "op": "insert",
            "ts": "2026-05-01T10:00:00Z",
            "id": "r20260501100000",
            "values": {"name": "Apt A", "amount": 1200, "status": "new"},
        }
    ]
    (sheet_dir / "ops.jsonl").write_text(json.dumps(ops[0]) + "\n")
    rebuild_state(sheet_dir)

    (sheet_dir / "ops.jsonl").write_text("")
    rebuild_state(sheet_dir)

    db = sqlite3.connect(str(sheet_dir / "state.sqlite"))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM rows").fetchall()
    db.close()
    assert rows == []
