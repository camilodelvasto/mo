"""Build a webapp: run the build the folder declares in webapp.yaml, return its output.

The shape knows no engine. The folder says which commands build it and where the
static site lands; deploy hands that folder to the adapter like any other shape's.
"""
import json
import subprocess
import time
from pathlib import Path

import jsonschema
import yaml

DECLARATION = "webapp.yaml"
SCHEMA = Path(__file__).parent.parent / "schemas" / "webapp.v1.json"


class WebappError(Exception):
    pass


def _declaration(app: Path) -> dict:
    path = app / DECLARATION
    if not path.is_file():
        raise WebappError(f"{path}: missing — a webapp declares its build in {DECLARATION}")
    declared = yaml.safe_load(path.read_text())
    try:
        jsonschema.validate(declared, json.loads(SCHEMA.read_text()))
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise WebappError(f"{path}: {where}: {e.message}") from e
    return declared


def _check_settings(encrypted, mnemonic, rotate, service_worker, crawlable) -> None:
    """A static webapp ships its own output as built. Settings that would change it throw."""
    if encrypted:
        raise WebappError("encrypted: true — a webapp ships its own output, unencrypted")
    if mnemonic is not None:
        raise WebappError("mnemonic given — a webapp is not encrypted")
    if rotate:
        raise WebappError("rotate: true — a webapp is not encrypted")
    if service_worker:
        raise WebappError("service_worker: true — a webapp owns its service worker, if any")
    if crawlable != "none":
        raise WebappError(f"crawlable: {crawlable} — a webapp writes no crawler pages; only 'none'")


def _output(app: Path, out: str) -> Path:
    path = (app / out).resolve()
    if path == app.resolve() or app.resolve() not in path.parents:
        raise WebappError(f"{app / DECLARATION}: out: {out} — must be a folder inside the webapp")
    return app / out


def _run(app: Path, command: list) -> None:
    shown = " ".join(command)
    try:
        done = subprocess.run(command, cwd=app, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise WebappError(f"{app}: {shown}: command not found") from e
    if done.returncode != 0:
        raise WebappError(f"{app}: {shown}: exit {done.returncode}\n{done.stdout}{done.stderr}")


def build(content_path: Path, instance_name: str, corpus_root: Path, *,
          encrypted: bool, mnemonic: str | None, rotate: bool,
          service_worker: bool, crawlable: str) -> tuple:
    """Run the declared build in content_path. Returns (output folder, None)."""
    app = Path(content_path)
    _check_settings(encrypted, mnemonic, rotate, service_worker, crawlable)
    declared = _declaration(app)
    out = _output(app, declared["out"])

    started = time.time()
    for command in declared["build"]:
        _run(app, command)

    index = out / "index.html"
    if not index.is_file():
        raise WebappError(f"{index}: missing after the build — out: {declared['out']} must hold index.html")
    if index.stat().st_mtime < started:
        raise WebappError(f"{index}: not written by this build — out: {declared['out']} holds an older output")
    return out, None


def run(corpus_root: Path, instance_name: str, args: list) -> None:
    """mo webapp build <path> — the local build, as a deploy runs it with no target settings."""
    if len(args) != 1:
        raise SystemExit("Usage: mo webapp build <path>")
    out, _ = build(Path(args[0]).resolve(), instance_name, corpus_root,
                   encrypted=False, mnemonic=None, rotate=False,
                   service_worker=False, crawlable="none")
    print(out)
