# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapter: mo sheets tui <sheet>"""
import os
import sys
import threading
import time
from pathlib import Path


def run(corpus_root: Path, instance: str, args: list) -> None:
    if not args:
        print("Usage: mo sheets tui <sheet>")
        sys.exit(1)

    import requests
    import uvicorn

    from shapes.sheets.src.api import create_app
    from shapes.sheets.src.cli_utils import resolve_sheet, read_sheet_port, bind_port
    from shapes.sheets.src.watcher import watch_inbox

    sheet_dir = resolve_sheet(args[0], corpus_root)

    declared_port = read_sheet_port(sheet_dir)
    port = bind_port(declared_port)
    api_url = f"http://127.0.0.1:{port}"

    app = create_app(sheet_dir)
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

    from shapes.sheets.renderer.tui.app import SheetsApp
    tui = SheetsApp(sheet_dir, api_url=api_url)
    tui.set_watcher_callback()

    def on_processed():
        tui.call_from_thread(tui._load_rows)

    watcher_thread = threading.Thread(
        target=watch_inbox,
        args=(sheet_dir,),
        kwargs={
            "corpus_root": corpus_root,
            "api_url": api_url,
            "on_processed": on_processed,
        },
        daemon=True,
    )
    watcher_thread.start()

    try:
        tui.run()
    finally:
        os.system("stty sane 2>/dev/null; printf '\\e[?1004l\\e[?25h' 2>/dev/null")
