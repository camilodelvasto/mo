# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapter: mo sheets status"""
from pathlib import Path


def run(corpus_root: Path, instance: str, args: list) -> None:
    import requests
    from shapes.sheets.src.cli_utils import discover_sheets

    sheets = discover_sheets(corpus_root)
    if not sheets:
        print("No sheets found in content/")
        return

    dim = '\033[2m'
    cyan = '\033[36m'
    green = '\033[32m'
    red = '\033[31m'
    reset = '\033[0m'

    for s in sheets:
        port = s["port"]
        name = s["name"]

        if port:
            try:
                resp = requests.get(f"http://127.0.0.1:{port}/api/rows", timeout=1)
                if resp.ok:
                    status = f"{green}● running{reset}"
                    url = f"{cyan}http://localhost:{port}{reset}"
                else:
                    status = f"{red}○ stopped{reset}"
                    url = f"{dim}http://localhost:{port}{reset}"
            except Exception:
                status = f"{red}○ stopped{reset}"
                url = f"{dim}http://localhost:{port}{reset}"
        else:
            status = f"{dim}○ no port{reset}"
            url = f"{dim}(ephemeral){reset}"

        print(f"  {name:<20} {url:<40} {status}")
