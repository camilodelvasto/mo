# cli/deploy/stack.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The stack rail of `mo deploy` — thin and mechanism-agnostic. It does the
stack-shape prep (resolve, the required-cap rule, the config compile), resolves
the converge adapter the target declares (`converge:`), and dispatches. It makes
NO docker/ssh/compose call — every such operation is the resolved adapter's. It
owns the exit policy: an adapter ConvergeError becomes a non-zero exit with the
adapter's named message. Never enters the copy-adapter machinery (no dist_path,
no publish_path, no URL)."""
import sys
from pathlib import Path

import yaml

from cli.infra.box_layout import box_layout, corpus_volume
from cli.infra.resolver import resolve_credentials
from cli.deploy.caps import required_caps, bound_caps, shims_present, attest_required
from cli.deploy.smoke import smoke_models
from cli.deploy.aws_creds import resolve_aws_creds
from cli.deploy import converge
from corpus_server import compile as cs_compile


def _read(corpus_root: Path, rel: str) -> str:
    return (corpus_root / rel).read_text()


def _load_ask_yaml(corpus_root: Path, env: dict) -> dict:
    return yaml.safe_load((corpus_root / env["content"] / "ask.yaml").read_text())


def resolve_attest_secret(corpus_root: Path, env: dict, ask_yaml: dict) -> str:
    """The box's attachment-signing secret, read from the path the env declares.
    Required exactly when an exposed ask accepts attachments — a box that ships
    without it answers every /verify with a 500. Never generated here: a fresh
    secret would invalidate every attachment already held in a visitor's browser.
    A box that serves no attachments returns "" (the mount still happens; an empty
    secret is refused by name at runtime, never guessed)."""
    if not attest_required(ask_yaml, env["exposed_asks"]):
        return ""
    rel = env.get("attest_secret")
    if not rel:
        raise SystemExit(
            "an exposed ask accepts attachments but the stack env declares no "
            "'attest_secret' — the box signs every verified image with it. Generate "
            "one (python3 -c \"import secrets;print(secrets.token_hex(32))\") into the "
            "secrets tree and declare its path; it must stay stable, a new secret "
            "invalidates every image a visitor still holds")
    path = corpus_root / rel
    if not path.is_file():
        raise SystemExit(f"attest_secret {rel} is declared but not present at {path}")
    secret = path.read_text().strip()
    if not secret:
        raise SystemExit(f"attest_secret {rel} is empty")
    return secret


def _grove_origins(env: dict) -> list:
    """The CORS origins Caddy answers — the single read site for the reverse-origin
    seam (spec §6). No default: must be declared."""
    if "grove_origins" not in env:
        if "grove_origin" in env:
            raise SystemExit("stack env declares 'grove_origin' (one value) — it is now "
                             "'grove_origins:', a list of every grove origin the box answers")
        raise SystemExit("stack env has no 'grove_origins' — declare the CORS origins "
                         "of the groves this box answers")
    return env["grove_origins"]


def run(corpus_root: Path, target: dict, env: dict, remote: dict,
        env_name: str) -> None:
    remote = {**remote, **resolve_credentials(remote, env["remote"], corpus_root)}
    layout = box_layout(remote)
    volume = corpus_volume(layout["root"], env["corpus"])
    print(f"deploy stack {target['stack']} {env_name} → {remote['host']}",
          file=sys.stderr)

    # --- stack-shape gates, all local (no box) ---
    capabilities = yaml.safe_load(_read(corpus_root, env["capabilities"]))
    ask_yaml = _load_ask_yaml(corpus_root, env)
    need = required_caps(ask_yaml, env["exposed_asks"])
    missing = need - bound_caps(capabilities)
    if missing:
        raise SystemExit(f"exposed asks need capabilities the committed "
                         f"{env['capabilities']} doesn't bind: {sorted(missing)}")
    shims_present(capabilities, corpus_root)
    print("  generation smoke (1-token converse per model)…", file=sys.stderr)
    try:
        smoke_models(env["aws_profile"], capabilities)          # the completion gate
    except Exception as e:
        raise SystemExit(f"generation smoke failed — the box could not answer: {e}")

    # --- resolve secrets (in-memory; never disk/argv/log) ---
    aws_creds = resolve_aws_creds(env["aws_profile"])
    access_csv = _read(corpus_root, env["auth"]["access_list"])
    attest_secret = resolve_attest_secret(corpus_root, env, ask_yaml)

    dotenv, gate = cs_compile.render(
        env, grove_origins=_grove_origins(env),
        aws_credentials_file=layout["aws_creds"], host_root=layout["root"],
        sites_dir=layout["sites"])

    adapter = converge.resolve(target["converge"])
    try:
        adapter.converge(corpus_root, remote, layout,
                         dotenv=dotenv, gate_yaml=yaml.dump(gate, sort_keys=False),
                         capabilities_yaml=_read(corpus_root, env["capabilities"]),
                         access_csv=access_csv, aws_creds=aws_creds,
                         attest_secret=attest_secret, volume=volume)
    except converge.ConvergeError as e:
        print(str(e), file=sys.stderr); sys.exit(1)
    print("✓ deployed: converged, healthy, generation proven", file=sys.stderr)
