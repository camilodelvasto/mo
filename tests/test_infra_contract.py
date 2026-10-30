# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The hetzner adapter and the committed corpus-server stack agree by contract:
the Caddyfile carries the grove-sites import the adapter rewrites, compose mounts
the sites root where the adapter's snippets point, the Caddy config is a
directory mount (a shipped file is a new inode), and the compile writes the same
SITES_DIR the adapter uploads into."""
from pathlib import Path

from cli.infra.box_layout import box_layout
from corpus_server.compile import render
from shapes.shared.adapters.hetzner import CONTAINER_SITES, _validation_caddyfile

_STACK = Path(__file__).resolve().parent.parent / "infrastructure" / "corpus-server"


def test_committed_caddyfile_carries_the_import_the_adapter_rewrites():
    _validation_caddyfile((_STACK / "caddy" / "Caddyfile").read_text(), "/x")   # raises if not


def test_compose_mounts_sites_and_the_caddy_dir():
    compose = (_STACK / "docker-compose.yml").read_text()
    assert f"${{SITES_DIR:?compile writes SITES_DIR}}:{CONTAINER_SITES}:ro" in compose
    assert "./caddy:/etc/caddy:ro" in compose
    assert "./Caddyfile:" not in compose          # no single-file mount (stale inode)


def test_compile_sites_dir_is_the_layout_sites_root():
    layout = box_layout({"host": "h", "user": "u", "path": "/opt/cs"})
    env = {"domain": "ask.example", "corpus": "cx", "exposed_asks": ["chat"],
           "auth": {"scheme": "none"}, "roles": {"r": {"cap": 5}},
           "default_role": "r", "window": "month",
           "rate_limit": {"per_minute": 60, "block_after": 10, "block_for": "15m"}}
    dotenv, _ = render(env, grove_origins=["https://www.moui.io"],
                       aws_credentials_file=layout["aws_creds"],
                       host_root=layout["root"], sites_dir=layout["sites"])
    assert f"SITES_DIR={layout['sites']}" in dotenv.splitlines()


def _compose() -> dict:
    import yaml
    return yaml.safe_load((_STACK / "docker-compose.yml").read_text())


def test_caddy_image_is_pinned_to_a_minor():
    import re
    image = _compose()["services"]["caddy"]["image"]
    # the CORS echo and handle_errors rewrite were verified on 2.11; a bare caddy:2
    # moves to whatever 2.x ships next
    assert re.fullmatch(r"caddy:2\.\d+(\.\d+)?", image), image


def _dotenv_keys(dotenv: str) -> set:
    return {line.split("=", 1)[0] for line in dotenv.splitlines() if "=" in line}


def test_grove_origin_re_is_one_name_across_compile_compose_and_caddyfile():
    layout = box_layout({"host": "h", "user": "u", "path": "/opt/cs"})
    env = {"domain": "ask.example", "corpus": "cx", "exposed_asks": ["chat"],
           "auth": {"scheme": "none"}, "roles": {"r": {"cap": 5}},
           "default_role": "r", "window": "month",
           "rate_limit": {"per_minute": 60, "block_after": 10, "block_for": "15m"}}
    dotenv, _ = render(env, grove_origins=["https://www.moui.io"],
                       aws_credentials_file=layout["aws_creds"],
                       host_root=layout["root"], sites_dir=layout["sites"])
    assert "GROVE_ORIGIN_RE" in _dotenv_keys(dotenv)
    caddy_env = _compose()["services"]["caddy"]["environment"]
    assert caddy_env["GROVE_ORIGIN_RE"].startswith("${GROVE_ORIGIN_RE:?")
    assert "{$GROVE_ORIGIN_RE}" in (_STACK / "caddy" / "Caddyfile").read_text()


def test_layout_caddyfile_is_the_shipped_caddyfile():
    layout = box_layout({"host": "h", "user": "u", "path": "/opt/cs"})
    rel = Path(layout["caddyfile"]).relative_to(layout["compose_dir"])
    assert rel == Path("caddy/Caddyfile")
    assert (_STACK / rel).is_file()


def test_caddy_reload_reads_the_caddyfile_through_the_config_dir_mount(monkeypatch):
    import re
    from cli.sync.corpus import box
    cmds = []
    monkeypatch.setattr(box, "ssh_exec", lambda remote, cmd: cmds.append(cmd) or "")
    box.caddy_reload({"host": "h"}, "/opt/cs/infrastructure/corpus-server", "/opt/cs/box-config/.env")
    [config] = re.findall(r"--config (\S+)", cmds[0])
    mounts = [v.split(":") for v in _compose()["services"]["caddy"]["volumes"]]
    [(source, target, _)] = [m for m in mounts if m[0] == "./caddy"]
    layout = box_layout({"host": "h", "user": "u", "path": "/opt/cs"})
    in_dir = Path(layout["caddyfile"]).relative_to(Path(layout["compose_dir"]) / source)
    assert config == f"{target}/{in_dir.as_posix()}"
