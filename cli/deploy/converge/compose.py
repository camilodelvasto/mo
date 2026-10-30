# cli/deploy/converge/compose.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The docker-compose-over-SSH converge mechanism — one member of the converge
registry. Owns EVERY docker/ssh/compose operation: presence preflight, bundle
staging (including capabilities.yaml), ship, secret placement, scaffold, up -d
--build, Caddy reload, the health-gate, the build-cache prune. The box.* ssh
toolkit is this adapter's implementation detail; the rail makes none of these calls. Fail-closed: every failure is a
ConvergeError with a named message, and the rail translates it to a non-zero exit."""
import sys
import tempfile
from pathlib import Path

from cli.deploy.bundle import stage_bundle
from cli.deploy.converge import ConvergeError
from cli.sync.corpus import box
from cli.sync.corpus.box import ssh_exec, BoxError

_HEALTH_TIMEOUT_S = 600   # sized for the COLD first build-on-box (deps pull on a
                          # cold layer cache); do NOT tighten to the warm-case number.
_BUILD_CACHE_MAX = "2GB"  # one warm set of gate + serve dependency layers: the next
                          # deploy rebuilds warm, the cache stops growing per deploy.


def _present(remote, target, label):
    try:
        ssh_exec(remote, target)
    except BoxError:
        raise ConvergeError(f"box not provisioned: {label} → run the provision "
                            f"runbook, not deploy")


def _preflight_presence(remote, layout):
    _present(remote, "docker --version", "Docker not present")
    _present(remote, f'test -d "{layout["compose_dir"]}"',
             f'compose_dir missing ({layout["compose_dir"]})')


def converge(corpus_root, remote, layout, *, dotenv, gate_yaml, capabilities_yaml,
             access_csv, aws_creds, attest_secret, volume) -> None:
    _preflight_presence(remote, layout)                                    # a
    stage = stage_bundle(corpus_root, dotenv, gate_yaml,
                         Path(tempfile.mkdtemp()))                         # c (logic only)
    box.ship(remote, stage, layout["root"])                                # d
    box.put_file(remote, access_csv, f'{layout["box_config"]}/access.csv')  # d2 gate-only
    box.put_file(remote, aws_creds, layout["aws_creds"])                   # d2 serve-only
    box.put_file(remote, attest_secret, layout["attest_secret"])           # d2 serve-only;
    #   the compose mount is unconditional (compose cannot branch on a declaration),
    #   so a box serving no attachments gets an empty file — /verify then refuses by
    #   name ("attest secret is empty") instead of signing with a guessed value.
    box.put_file(remote, capabilities_yaml, layout["capabilities"])        # d2 serve-only;
    #   put_file (cat >) truncates the mounted inode in place → live caps updates,
    #   unlike the tar bundle which replaces the inode and goes stale on a file mount.
    box.run_volume_op(remote, "scaffold", volume)                          # e
    ssh_exec(remote, f'mkdir -p "{layout["sites"]}"')                       # e2 grove sites root
    ssh_exec(remote, f'rm -f "{layout["compose_dir"]}/Caddyfile"')          # e3 orphan: the
    #   Caddyfile moved into ./caddy (a directory mount); the tar ship never deletes.
    ssh_exec(remote, f'rm -rf "{layout["compose_dir"]}/dev"')               # e4 earlier bundles
    #   shipped dev/ (local access.csv, attest.secret, ledgers); the bundle no longer does.
    try:                                                                    # f
        box.compose_up(remote, layout["compose_dir"], layout["env_file"])
    except BoxError as e:
        raise ConvergeError(f"converge failed: docker compose could not bring the "
                            f"stack up — {e}")
    try:                                                                    # f2
        box.caddy_reload(remote, layout["compose_dir"], layout["env_file"])
    except BoxError as e:
        raise ConvergeError(f"stack up, caddy reload rejected the shipped Caddyfile: {e}")
    # Corpus-aware health (g): a cold box (no `current`) is "up, awaiting corpus",
    # not unhealthy — the find-healthcheck needs a corpus, which is sync's job.
    if box.current_digest(remote, volume) is None:
        _prune(remote, "stack up, awaiting corpus")
        print("✓ stack up — awaiting `mo sync corpus` (no corpus on the box yet)",
              file=sys.stderr)
        return
    try:
        box.confirm_healthy(remote, timeout_s=_HEALTH_TIMEOUT_S,
                            compose_dir=layout["compose_dir"],
                            env_file=layout["env_file"])
    except BoxError:
        raise ConvergeError(
            f"converge succeeded, healthcheck failed within {_HEALTH_TIMEOUT_S}s "
            f"— the stack is down; redeploy the previous commit or investigate")
    _prune(remote, "stack up and healthy")


def _prune(remote, state):
    # (h) only once the stack is up: a failed deploy keeps its cache, so the retry
    # builds warm.
    try:
        box.prune_build_cache(remote, _BUILD_CACHE_MAX)
    except BoxError as e:
        raise ConvergeError(f"{state}; build-cache prune failed: {e}")
