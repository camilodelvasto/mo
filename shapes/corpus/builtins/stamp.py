# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""engine.stamp — create the intrinsic description. Reads, never alters."""
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from shapes.corpus.engine import identity
from shapes.corpus.engine.errors import StageFailure


def run(pair_dir: Path, stage: dict, input_path: Path) -> dict:
    mime, _ = mimetypes.guess_type(input_path.name)
    if mime is None:
        raise StageFailure(stage["id"], f"unsupported type: {input_path.name}")
    st = input_path.stat()   # st_ctime: birth time on macOS, inode-change on Linux
    iso = lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return {
        "fields": {
            "source_name": input_path.name,
            "mime": mime,
            "hash": identity.sha256_file(input_path),
            "size": st.st_size,
            "createdAt": iso(st.st_ctime),
            "modifiedAt": iso(st.st_mtime),
        },
        "output": None,
        "meters": {},
    }
