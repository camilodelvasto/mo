# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from cli.infra.box_layout import box_layout, corpus_volume


def _remote():
    return {"host": "ask.moui.co", "user": "root", "path": "/opt/corpus-server"}


def test_box_layout_derives_host_paths_from_path():
    L = box_layout(_remote())
    assert L["root"] == "/opt/corpus-server"
    assert L["compose_dir"] == "/opt/corpus-server/infrastructure/corpus-server"
    assert L["env_file"] == "/opt/corpus-server/box-config/.env"
    assert L["box_config"] == "/opt/corpus-server/box-config"
    assert L["capabilities"] == "/opt/corpus-server/capabilities.yaml"


def test_corpus_volume_is_root_plus_corpus():
    assert corpus_volume("/opt/corpus-server", "acme-notes") == \
        "/opt/corpus-server/corpus/acme-notes"


def test_box_layout_aws_creds_is_persistent_host_path():
    from cli.infra.box_layout import box_layout
    L = box_layout({"host": "h", "user": "u", "path": "/opt/corpus-server"})
    assert L["aws_creds"] == "/opt/corpus-server/secrets/aws"


def test_missing_path_fails_loud_named():
    # "named" = the error names BOTH the gap and the offending host, so the
    # operator knows which remote to fix. Assert both, not just the gap.
    with pytest.raises(ValueError, match=r"elections-box.*no 'path'"):
        box_layout({"host": "elections-box", "user": "u"})


def test_box_layout_attest_secret_is_a_persistent_serve_path():
    # The box signs every canonical attachment with it; serve reads it at
    # <machine_root>/attest.secret, and machine_root in the container is /app —
    # the same place capabilities.yaml mounts.
    L = box_layout({"host": "h", "user": "u", "path": "/opt/corpus-server"})
    assert L["attest_secret"] == "/opt/corpus-server/secrets/attest.secret"


def test_box_layout_sites_is_the_static_sites_root():
    # The hetzner adapter writes groves here; the stack mounts it into Caddy at
    # /srv/sites. One derivation, both sides agree by construction.
    L = box_layout(_remote())
    assert L["sites"] == "/opt/corpus-server/sites"


def test_box_layout_caddyfile_sits_in_the_mounted_caddy_dir():
    # compose mounts ./caddy as a DIRECTORY at /etc/caddy, so a shipped
    # Caddyfile (new inode) is what the next reload reads.
    L = box_layout(_remote())
    assert L["caddyfile"] == "/opt/corpus-server/infrastructure/corpus-server/caddy/Caddyfile"
