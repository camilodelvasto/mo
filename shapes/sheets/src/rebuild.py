import json
import sqlite3
from pathlib import Path

import yaml

from shapes.sheets.src.fields import Field, parse_fields

FIELD_TYPE_MAP = {
    "primary": "TEXT PRIMARY KEY",
    "string": "TEXT",
    "text": "TEXT",
    "number": "REAL",
    "datetime": "TEXT",
    "date": "TEXT",
    "enum": "TEXT",
    "integer": "INTEGER",
    "boolean": "INTEGER",
    "log": "TEXT",
}


def _column_def(field: Field) -> str:
    mapped = FIELD_TYPE_MAP.get(field.type)
    if not mapped:
        raise ValueError(f"Unknown field type: {field.type}")
    return f"{field.name} {mapped}"


def rebuild_state(content_dir: Path) -> None:
    content_dir = Path(content_dir)
    sheet = yaml.safe_load((content_dir / "sheet.yaml").read_text())
    fields = parse_fields(sheet)

    db_path = content_dir / "state.sqlite"
    ops_path = content_dir / "ops.jsonl"

    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    columns = [_column_def(f) for f in fields]
    conn.execute(f"CREATE TABLE rows ({', '.join(columns)})")
    known_columns = {f.name for f in fields}

    if ops_path.exists():
        text = ops_path.read_text().strip()
        if text:
            for line in text.splitlines():
                op = json.loads(line)
                _apply_op(conn, op, known_columns)

    conn.commit()
    conn.close()


def _apply_op(conn: sqlite3.Connection, op: dict, known_columns: set[str] | None = None) -> None:
    if op["op"] == "insert":
        values = op["values"]
        if known_columns is not None:
            values = {k: v for k, v in values.items() if k in known_columns}
        cols = list(values.keys()) + ["id"]
        vals = list(values.values()) + [op["id"]]
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO rows ({', '.join(cols)}) VALUES ({placeholders})", vals
        )
    elif op["op"] == "update":
        values = op["values"]
        if known_columns is not None:
            values = {k: v for k, v in values.items() if k in known_columns}
        if not values:
            return
        sets = ", ".join(f"{k} = ?" for k in values)
        vals = list(values.values()) + [op["id"]]
        conn.execute(f"UPDATE rows SET {sets} WHERE id = ?", vals)
    elif op["op"] == "append":
        field_name = op["field"]
        row = conn.execute("SELECT * FROM rows WHERE id = ?", (op["id"],)).fetchone()
        current = json.loads(row[field_name] or "[]") if row else []
        current.append(op["entry"])
        conn.execute(
            f"UPDATE rows SET {field_name} = ? WHERE id = ?",
            (json.dumps(current, ensure_ascii=False), op["id"]),
        )
