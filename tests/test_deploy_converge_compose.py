# tests/test_deploy_converge_compose.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from pathlib import Path
import cli.deploy.converge as converge
from cli.deploy.converge import ConvergeError, compose


def test_resolve_loads_named_adapter():
    mod = converge.resolve("compose")
    assert hasattr(mod, "converge")


def test_resolve_unknown_fails_loud():
    with pytest.raises(ConvergeError, match="podman"):
        converge.resolve("podman")


class FakeBox:
    def __init__(self): self.calls = []; self.puts = []; self._current = None
    def ship(self, *a): self.calls.append("ship")
    def run_volume_op(self, r, op, *a): self.calls.append(op)
    def compose_up(self, *a): self.calls.append("compose_up")
    def caddy_reload(self, *a): self.calls.append("caddy_reload")
    def confirm_healthy(self, *a, **k): self.calls.append("confirm")
    def put_file(self, r, content, dest): self.calls.append("put"); self.puts.append((content, dest))
    def current_digest(self, r, vol): return self._current
    def prune_build_cache(self, r, max_used): self.calls.append(("prune", max_used))


def _patch(monkeypatch, fake):
    monkeypatch.setattr(compose, "box", fake)
    monkeypatch.setattr(compose, "ssh_exec", lambda r, cmd: "")   # presence checks pass
    monkeypatch.setattr(compose, "stage_bundle",
                        lambda root, dotenv, gate, stage: stage)
    monkeypatch.setattr(compose.tempfile, "mkdtemp", lambda: "/tmp/stage")


def _call(fake):
    compose.converge(Path("/root"), {"host": "h", "path": "/opt/cs"},
                     {"root": "/opt/cs", "compose_dir": "/opt/cs/infra",
                      "env_file": "/opt/cs/box-config/.env",
                      "box_config": "/opt/cs/box-config", "aws_creds": "/opt/cs/secrets/aws",
                      "attest_secret": "/opt/cs/secrets/attest.secret",
                      "capabilities": "/opt/cs/capabilities.yaml",
                      "sites": "/opt/cs/sites"},
                     dotenv="e\n", gate_yaml="g\n", capabilities_yaml="capabilities: {}\n",
                     access_csv="id,code\n", aws_creds="[default]\n",
                     attest_secret="d34db33f", volume="/opt/cs/corpus/cx")


def test_converge_places_all_secrets_then_converges(monkeypatch):
    fake = FakeBox(); fake._current = "deadbeef"; _patch(monkeypatch, fake); _call(fake)
    assert fake.calls == ["ship", "put", "put", "put", "put", "scaffold", "compose_up",
                          "caddy_reload", "confirm", ("prune", "2GB")]
    dests = {d for _, d in fake.puts}
    assert dests == {"/opt/cs/box-config/access.csv", "/opt/cs/secrets/aws",
                     "/opt/cs/secrets/attest.secret", "/opt/cs/capabilities.yaml"}


def test_secrets_go_to_least_exposure_paths(monkeypatch):
    fake = FakeBox(); fake._current = "deadbeef"; _patch(monkeypatch, fake); _call(fake)
    by_dest = {d: c for c, d in fake.puts}
    assert by_dest["/opt/cs/box-config/access.csv"] == "id,code\n"   # gate-readable
    assert by_dest["/opt/cs/secrets/aws"] == "[default]\n"           # serve-readable
    assert by_dest["/opt/cs/capabilities.yaml"] == "capabilities: {}\n"  # serve-readable, live via put_file


def test_health_timeout_is_defined_down(monkeypatch):
    from cli.sync.corpus.box import BoxError
    fake = FakeBox()
    fake._current = "deadbeef"
    fake.confirm_healthy = lambda *a, **k: (_ for _ in ()).throw(BoxError("x"))
    _patch(monkeypatch, fake)
    with pytest.raises(ConvergeError, match="healthcheck failed"):
        _call(fake)


def test_cold_box_skips_health_reports_awaiting_corpus(monkeypatch):
    fake = FakeBox(); _patch(monkeypatch, fake)   # _current stays None
    _call(fake)                                    # no raise
    assert "confirm" not in fake.calls             # find-health skipped on a cold box


def test_warm_box_health_gates(monkeypatch):
    fake = FakeBox(); _patch(monkeypatch, fake); fake._current = "deadbeefdeadbeef"
    _call(fake)
    assert fake.calls[-2:] == ["confirm", ("prune", "2GB")]   # current present → confirm_healthy


def test_compose_up_failure_is_defined_down(monkeypatch):
    from cli.sync.corpus.box import BoxError
    fake = FakeBox()
    fake.compose_up = lambda *a, **k: (_ for _ in ()).throw(BoxError("build error"))
    _patch(monkeypatch, fake)
    with pytest.raises(ConvergeError, match="could not bring the stack up"):
        _call(fake)


# --- the attachment-signing secret ------------------------------------------------
# It rides the same path as the aws key: resolved by the rail, placed serve-only,
# never on an argv. The mount is unconditional (compose cannot branch), so a box
# that serves no attachments still gets the file — empty, which /verify refuses
# by name rather than signing with a guessed value.

def _call_with_attest(fake, attest_secret):
    compose.converge(Path("/root"), {"host": "h", "path": "/opt/cs"},
                     {"root": "/opt/cs", "compose_dir": "/opt/cs/infra",
                      "env_file": "/opt/cs/box-config/.env",
                      "box_config": "/opt/cs/box-config", "aws_creds": "/opt/cs/secrets/aws",
                      "attest_secret": "/opt/cs/secrets/attest.secret",
                      "capabilities": "/opt/cs/capabilities.yaml",
                      "sites": "/opt/cs/sites"},
                     dotenv="e\n", gate_yaml="g\n", capabilities_yaml="capabilities: {}\n",
                     access_csv="id,code\n", aws_creds="[default]\n",
                     attest_secret=attest_secret, volume="/opt/cs/corpus/cx")


def test_attest_secret_is_placed_serve_only(monkeypatch):
    fake = FakeBox(); fake._current = "deadbeef"; _patch(monkeypatch, fake)
    _call_with_attest(fake, "d34db33f")
    by_dest = {d: c for c, d in fake.puts}
    assert by_dest["/opt/cs/secrets/attest.secret"] == "d34db33f"


def test_a_box_without_attachments_still_gets_the_file_empty(monkeypatch):
    fake = FakeBox(); fake._current = "deadbeef"; _patch(monkeypatch, fake)
    _call_with_attest(fake, "")
    by_dest = {d: c for c, d in fake.puts}
    assert by_dest["/opt/cs/secrets/attest.secret"] == ""


def test_converge_creates_the_sites_root_before_compose_up(monkeypatch):
    # compose bind-mounts ${SITES_DIR}; it must exist (owned, not docker-created)
    # before `up` so Caddy's `import /srv/sites/*.caddy` sees the adapter's files.
    from cli.infra.box_layout import box_layout
    fake = FakeBox(); fake._current = "deadbeef"; _patch(monkeypatch, fake)
    cmds = []
    monkeypatch.setattr(compose, "ssh_exec",
                        lambda r, cmd: cmds.append(cmd) or fake.calls.append(cmd) or "")
    compose.converge(Path("/root"), {"host": "h", "user": "u", "path": "/opt/cs"},
                     box_layout({"host": "h", "user": "u", "path": "/opt/cs"}),
                     dotenv="e\n", gate_yaml="g\n", capabilities_yaml="capabilities: {}\n",
                     access_csv="id,code\n", aws_creds="[default]\n",
                     attest_secret="d34db33f", volume="/opt/cs/corpus/cx")
    assert any('mkdir -p "/opt/cs/sites"' in c for c in cmds)
    mkdir = fake.calls.index('mkdir -p "/opt/cs/sites"')
    assert mkdir < fake.calls.index("compose_up")


# --- Caddy picks up a shipped Caddyfile ----------------------------------------
# `up -d` leaves an unchanged caddy service running, and Caddy reads its config
# only at start or on reload — so a Caddyfile-only deploy needs the reload.

def test_converge_reloads_caddy_right_after_compose_up(monkeypatch):
    fake = FakeBox(); fake._current = "deadbeef"; _patch(monkeypatch, fake); _call(fake)
    assert fake.calls.index("caddy_reload") == fake.calls.index("compose_up") + 1


def test_caddy_reload_failure_is_a_named_converge_error(monkeypatch):
    from cli.sync.corpus.box import BoxError
    fake = FakeBox(); fake._current = "deadbeef"
    fake.caddy_reload = lambda *a: (_ for _ in ()).throw(BoxError("adapting config: bad"))
    _patch(monkeypatch, fake)
    with pytest.raises(ConvergeError, match="stack up, caddy reload rejected the shipped "
                                            "Caddyfile: adapting config: bad") as exc:
        _call(fake)
    # a first deploy recreates caddy: there is no "previous config" to claim
    assert "previous" not in str(exc.value)


def test_box_caddy_reload_command(monkeypatch):
    from cli.sync.corpus import box as real_box
    cmds = []
    monkeypatch.setattr(real_box, "ssh_exec", lambda r, cmd: cmds.append(cmd) or "")
    real_box.caddy_reload({"host": "h"}, "/opt/cs/infra", "/opt/cs/box-config/.env")
    assert cmds == ['cd "/opt/cs/infra" && docker compose --env-file "/opt/cs/box-config/.env" '
                    'exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile']


def test_converge_removes_the_orphaned_root_caddyfile_before_compose_up(monkeypatch):
    # The Caddyfile moved into ./caddy (a directory mount); the tar ship never
    # deletes, so the old root-level copy is removed by name.
    fake = FakeBox(); fake._current = "deadbeef"; _patch(monkeypatch, fake)
    monkeypatch.setattr(compose, "ssh_exec", lambda r, cmd: fake.calls.append(cmd) or "")
    _call(fake)
    rm = 'rm -f "/opt/cs/infra/Caddyfile"'
    assert rm in fake.calls
    assert fake.calls.index(rm) < fake.calls.index("compose_up")


def test_converge_removes_dev_data_shipped_by_earlier_bundles(monkeypatch):
    fake = FakeBox(); fake._current = "deadbeef"; _patch(monkeypatch, fake)
    monkeypatch.setattr(compose, "ssh_exec", lambda r, cmd: fake.calls.append(cmd) or "")
    _call(fake)
    rm = 'rm -rf "/opt/cs/infra/dev"'
    assert rm in fake.calls
    assert fake.calls.index(rm) < fake.calls.index("compose_up")


# --- build cache ---------------------------------------------------------------
# Every stack deploy builds gate + serve on the box; nothing else ever clears the
# old layers (14 GB on the box, 2026-10-19). Pruned only once the stack is up, so
# a failed deploy keeps its cache and the retry builds warm.

def test_cold_box_prunes_once_the_stack_is_up(monkeypatch):
    fake = FakeBox(); _patch(monkeypatch, fake)   # _current stays None
    _call(fake)
    assert fake.calls[-2:] == ["caddy_reload", ("prune", "2GB")]


@pytest.mark.parametrize("failing", ["compose_up", "caddy_reload", "confirm_healthy"])
def test_a_failed_deploy_keeps_the_build_cache(monkeypatch, failing):
    from cli.sync.corpus.box import BoxError
    fake = FakeBox(); fake._current = "deadbeef"
    setattr(fake, failing, lambda *a, **k: (_ for _ in ()).throw(BoxError("x")))
    _patch(monkeypatch, fake)
    with pytest.raises(ConvergeError):
        _call(fake)
    assert not any(isinstance(c, tuple) and c[0] == "prune" for c in fake.calls)


def test_prune_failure_names_the_stack_state(monkeypatch):
    from cli.sync.corpus.box import BoxError
    fake = FakeBox(); fake._current = "deadbeef"
    fake.prune_build_cache = lambda *a: (_ for _ in ()).throw(BoxError("daemon busy"))
    _patch(monkeypatch, fake)
    with pytest.raises(ConvergeError, match="stack up and healthy; build-cache prune "
                                            "failed: daemon busy"):
        _call(fake)


def test_prune_failure_on_a_cold_box_names_the_stack_state(monkeypatch):
    from cli.sync.corpus.box import BoxError
    fake = FakeBox()
    fake.prune_build_cache = lambda *a: (_ for _ in ()).throw(BoxError("daemon busy"))
    _patch(monkeypatch, fake)
    with pytest.raises(ConvergeError, match="stack up, awaiting corpus; build-cache prune "
                                            "failed: daemon busy"):
        _call(fake)


def test_box_prune_build_cache_command(monkeypatch):
    from cli.sync.corpus import box as real_box
    cmds = []
    monkeypatch.setattr(real_box, "ssh_exec", lambda r, cmd: cmds.append(cmd) or "")
    real_box.prune_build_cache({"host": "h"}, "2GB")
    # --keep-storage is gone on Docker 29; image prune without -a drops only the
    # dangling gate/serve images each rebuild leaves behind.
    assert cmds == ["docker builder prune -f --max-used-space 2GB && docker image prune -f"]
