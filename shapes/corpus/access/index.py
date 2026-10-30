# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Open index/corpus.db inside the corpus. sqlite-vec + FTS5 + projection cache.
The ONLY module that opens the db. The vec table's dimension is fixed at
creation, so the schema is created lazily once dim is known."""
import sqlite3
from pathlib import Path

import sqlite_vec

from shapes.corpus.access.errors import AccessError

serialize = sqlite_vec.serialize_float32


def db_path(corpus: Path) -> Path:
    return corpus / "index" / "corpus.db"


def open_index(corpus: Path, dim: int | None = None) -> sqlite3.Connection:
    path = db_path(corpus)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.is_file()
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    # busy_timeout is connection-level and write-free — safe on read-only media.
    # Journal mode is a property of the DATABASE, set at creation (WAL) and
    # flipped to rollback when a snapshot ships to a read-only mount; opening
    # must never mutate it — the box serves the corpus from a :ro volume.
    conn.execute("PRAGMA busy_timeout=30000")
    if fresh:
        _create_schema(conn, dim)
    return conn


def _create_schema(conn: sqlite3.Connection, dim: int | None) -> None:
    # WAL from birth: readers (the catalogue search) never block behind a
    # vector-writing reconcile. A fresh db is on writable media by definition;
    # ship-time flips it to rollback for read-only mounts (sync snapshot).
    conn.execute("PRAGMA journal_mode=WAL")
    base = """
        CREATE TABLE docs (doc_id TEXT PRIMARY KEY, meta_hash TEXT NOT NULL);
        CREATE TABLE chunks (
            rowid INTEGER PRIMARY KEY,
            doc_id TEXT NOT NULL, ref TEXT NOT NULL,
            span_start INTEGER NOT NULL, span_end INTEGER NOT NULL,
            text TEXT NOT NULL);
        CREATE INDEX idx_chunks_doc ON chunks(doc_id);
        CREATE TABLE projection (doc_id TEXT PRIMARY KEY, folded TEXT NOT NULL);
        CREATE VIRTUAL TABLE fts_chunks USING fts5(text, content='chunks', content_rowid='rowid');
    """
    if dim is not None:
        vec = f"CREATE VIRTUAL TABLE vec_chunks USING vec0(doc_id TEXT, embedding float[{dim}]);"
        conn.executescript(base + vec)
    else:
        conn.executescript(base)
    conn.commit()
