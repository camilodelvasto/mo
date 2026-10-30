# cli/store/sqlite.py
"""Open and manage index.db and activity.db.

index.db schema (specified, not yet populated):
    bites: path, instance, shape, version, schema, theme, type, tags, mtime, fts
    assets: path, companion, mime, sha256, tags, mtime

STATUS: scaffold. Implementation follows when moui index is built."""
