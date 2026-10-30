# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The seam between the catalogue TUI and the CLI. Pure command builders (unit-
testable) plus thin async runners that shell out to `mo` and parse JSON. The TUI
holds no corpus logic — it invokes the CLI and renders what comes back."""
import asyncio
import json
import shutil
from pathlib import Path


def _mo() -> str:
    mo = shutil.which("mo")
    if mo is None:
        raise RuntimeError("`mo` is not on PATH; install the CLI with `pip install -e .`")
    return mo


def build_ask_cmd(mo: str, corpus: Path, ask_id: str, question: str,
                  *, grounding: float, mode: str, where: str) -> list:
    cmd = [mo, "corpus", "ask", str(corpus), ask_id, question,
           "--grounding", str(grounding), "--mode", mode, "--json"]
    if where:
        cmd += ["--where", where]
    return cmd


def build_save_cmd(mo: str, corpus: Path, name: str, definition: dict,
                   *, record: dict | None, definition_only: bool) -> tuple[list, str | None]:
    cmd = [mo, "corpus", "query", "save", str(corpus), name,
           "--ask", definition["ask"], "--question", definition["question"],
           "--grounding", str(definition["grounding"]), "--mode", definition["mode"]]
    if definition.get("where"):
        cmd += ["--where", definition["where"]]
    if definition_only:
        return cmd + ["--definition-only"], None
    return cmd, json.dumps(record, ensure_ascii=False)


async def _run(cmd: list, stdin: str | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate(stdin.encode() if stdin is not None else None)
    if proc.returncode != 0:
        # The CLI writes structured errors to stdout under --json; stderr may be empty.
        detail = err.decode().strip()
        if not detail:
            try:
                detail = json.loads(out.decode())["error"]["detail"]
            except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
                detail = out.decode().strip() or f"command failed: {' '.join(cmd)}"
        raise RuntimeError(detail)
    return out.decode()


async def run_ask(corpus: Path, ask_id: str, question: str,
                  *, grounding: float, mode: str, where: str) -> dict:
    cmd = build_ask_cmd(_mo(), corpus, ask_id, question,
                        grounding=grounding, mode=mode, where=where)
    return json.loads(await _run(cmd))


async def save_query(corpus: Path, name: str, definition: dict,
                     *, record: dict | None, definition_only: bool) -> str:
    cmd, stdin = build_save_cmd(_mo(), corpus, name, definition,
                                record=record, definition_only=definition_only)
    return (await _run(cmd, stdin)).strip()


async def list_queries(corpus: Path) -> list:
    return json.loads(await _run([_mo(), "corpus", "query", "list", str(corpus), "--json"]))
