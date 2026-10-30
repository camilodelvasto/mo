# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The single source of a corpus-server box's filesystem layout. Both the deploy
stack rail and the sync rail derive box-HOST paths here — never inline — so they
agree by construction, not by two call sites that read the same way today. Every
value returned is a box-host path (a docker mount SOURCE); the container paths
inside gate.yaml (fixed /data) are a separate space, owned by the compile. No
fallbacks: a remote without a declared deploy-root path fails loud here."""


def box_layout(remote: dict) -> dict:
    if "path" not in remote:
        raise ValueError(
            f"remote {remote.get('host', '?')} has no 'path' — a stack remote "
            f"must declare its deploy-root path (e.g. /opt/corpus-server)")
    root = remote["path"]
    return {
        "root": root,
        "compose_dir": f"{root}/infrastructure/corpus-server",
        # The committed Caddyfile, inside the ./caddy dir compose mounts at /etc/caddy
        # (a directory mount: the shipped file is a new inode, which a file mount
        # would never see).
        "caddyfile": f"{root}/infrastructure/corpus-server/caddy/Caddyfile",
        "env_file": f"{root}/box-config/.env",
        "box_config": f"{root}/box-config",
        "capabilities": f"{root}/capabilities.yaml",
        "aws_creds": f"{root}/secrets/aws",   # persistent (not tmpfs /run); deploy places the pulled key here
        # The box's attachment-signing secret. Mounted at /app/attest.secret, which is
        # serve's machine_root in the container — the same place capabilities.yaml goes.
        "attest_secret": f"{root}/secrets/attest.secret",
        # Static grove sites. The hetzner copy adapter writes releases + one
        # <domain>.caddy per domain here; compose mounts it read-only into Caddy
        # at /srv/sites, and the committed Caddyfile imports /srv/sites/*.caddy.
        "sites": f"{root}/sites",
    }


def corpus_volume(root: str, corpus: str) -> str:
    return f"{root}/corpus/{corpus}"
