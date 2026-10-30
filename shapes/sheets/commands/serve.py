# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapter: mo sheets serve <sheet>"""
import sys
import threading
import time
from pathlib import Path


def run(corpus_root: Path, instance: str, args: list) -> None:
    if not args:
        print("Usage: mo sheets serve <sheet>")
        sys.exit(1)

    import requests
    import uvicorn

    from shapes.sheets.src.api import create_app
    from shapes.sheets.src.cli_utils import resolve_sheet, read_sheet_port, bind_port
    from shapes.sheets.src.watcher import watch_inbox

    sheet_dir = resolve_sheet(args[0], corpus_root)
    core_dir = corpus_root / "shapes" / "sheets" / "renderer" / "core"

    declared_port = read_sheet_port(sheet_dir)
    port = bind_port(declared_port)
    api_url = f"http://127.0.0.1:{port}"

    app = create_app(sheet_dir, static_dir=core_dir if core_dir.exists() else None)

    api_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": port, "log_level": "warning"},
        daemon=True,
    )
    api_thread.start()

    for _ in range(50):
        try:
            requests.get(f"{api_url}/api/rows", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.1)

    watcher_thread = threading.Thread(
        target=watch_inbox,
        args=(sheet_dir,),
        kwargs={"corpus_root": corpus_root, "api_url": api_url},
        daemon=True,
    )
    watcher_thread.start()

    from cli.output import header, detail, done
    header("Serving:", sheet_dir.name)
    detail("URL:", f"http://localhost:{port}")
    detail("Sheet:", str(sheet_dir))
    done()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped")
