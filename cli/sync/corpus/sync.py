# cli/sync/corpus/sync.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Corpus sync orchestrator: fail-closed sequence from resolve to prune.

Entry point: run(corpus_root, target_ref, env_name, *, now)

The sequence:
  1. _resolve → remote + ctx
  2. acquire_lock (first action; try/finally release)
  3. _build_local_snapshot → snap_dir, digest, vid
  4. Idempotency: if current digest already matches, return early
  5. ship → validate_digest → verify_passport (pre-flip; BoxError → exit(1), no flip)
  6. flip → restart_serve
  7. confirm_healthy (BoxError → defined-down message + exit(1), no auto-rollback)
  8. prune (known-good depth)
"""
import sys
import tempfile
from pathlib import Path

from cli.infra.remotes import load_remotes, get_remote
from cli.infra.targets import load_target, get_environment, validate_remote_refs
from cli.infra.resolver import resolve_credentials
from cli.infra.box_layout import box_layout, corpus_volume
from cli.sync.corpus import snapshot, box
from cli.sync.corpus.box import BoxError
from shapes.corpus.access import index, reconcile


def _resolve(corpus_root: Path, target_ref: str, env_name: str) -> tuple[dict, dict]:
    """Resolve the deploy spine and build ctx.

    Returns (remote, ctx) where:
      remote — merged remote dict with host/user and optional ssh_key
      ctx    — {content, corpus, compose_dir, volume}
    """
    remotes = load_remotes(corpus_root)
    target = load_target(target_ref, corpus_root)
    validate_remote_refs(target, remotes)
    env = get_environment(target, env_name)
    remote = get_remote(remotes, env["remote"])
    credentials = resolve_credentials(remote, env["remote"], corpus_root)
    remote = {**remote, **credentials}

    corpus_name = env["corpus"]
    layout = box_layout(remote)
    ctx = {
        "content": str((corpus_root / env["content"]).resolve()),
        "corpus": corpus_name,
        "compose_dir": layout["compose_dir"],
        "env_file": layout["env_file"],
        "volume": corpus_volume(layout["root"], corpus_name),
        "exposed_asks": env["exposed_asks"],   # first one carries the ask smoke
    }
    return remote, ctx


def _build_local_snapshot(corpus_root: Path, ctx: dict, now: str) -> tuple[Path, str, str]:
    """Build a local snapshot, make its index consistent, and id it.

    Returns (snap_dir, digest, vid). snap_dir is a tempfile.mkdtemp() — caller
    owns cleanup (the snapshot is shipped then abandoned; temp dirs clean on reboot).

    A corpus is only valid to serve when its index matches its content. The box
    mounts the corpus READ-ONLY, so its per-ask reconcile must be a no-op — which
    requires a current index. So we reconcile the SNAPSHOT (the throwaway temp dir,
    never the operator's source) before computing the digest: shipping a stale index
    would make the box try to write on :ro and fail. Logged so a behind-its-content
    source index is visible, not silently corrected.
    """
    snap_dir = Path(tempfile.mkdtemp())
    snapshot.build_snapshot(Path(ctx["content"]), snap_dir)
    summary = reconcile.reconcile(snap_dir, corpus_root)
    if summary["embedded"] or summary["dropped"] or summary["refreshed"]:
        print(f"  reconciled snapshot index ({summary['embedded']} embedded, "
              f"{summary['dropped']} dropped, {summary['refreshed']} refreshed — "
              f"source index was behind its content)", file=sys.stderr)
    # Ship-mode: the box mounts the volume :ro, and a WAL database cannot even
    # be READ there (readers need the -shm file). Rollback journal is the only
    # medium-agnostic mode — flip the frozen snapshot's index before it ships.
    conn = index.open_index(snap_dir)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    digest = snapshot.canonical_digest(snap_dir)
    vid = snapshot.version_id(digest, now=now)
    return snap_dir, digest, vid


def run(corpus_root: Path, target_ref: str, env_name: str, *, now: str) -> None:
    """Fail-closed corpus sync sequence."""
    remote, ctx = _resolve(corpus_root, target_ref, env_name)
    print(f"sync corpus {target_ref} {env_name} → {remote['host']}", file=sys.stderr)
    lockfile = f'{ctx["volume"]}/.sync.lock'
    box.acquire_lock(remote, lockfile, label="sync", target_ref=target_ref)
    try:
        print("  building snapshot", file=sys.stderr)
        snap_dir, digest, vid = _build_local_snapshot(corpus_root, ctx, now)

        # Idempotency: compare 16-char digest suffix of current version
        cur = box.current_digest(remote, ctx["volume"])
        if cur == digest[:16]:
            print(f"  already current ({digest[:16]}) — nothing to ship", file=sys.stderr)
            return

        version_dir = f'{ctx["volume"]}/versions/{vid}'
        # Diff against the live version already on the box: rsync hardlinks every
        # unchanged (content-addressed) file, so only the changed index + new docs
        # cross the wire. None on first deploy (no current) → full transfer.
        link_dest = f'{ctx["volume"]}/current' if cur is not None else None
        print(f"  shipping → versions/{vid}", file=sys.stderr)
        box.ship_version(remote, snap_dir, version_dir, link_dest)
        box.validate_digest(remote, version_dir, digest)
        print("  digest ok; verifying passport in the serve container", file=sys.stderr)

        try:
            box.verify_passport(remote, f'/data/corpus/versions/{vid}',
                                ctx["compose_dir"], ctx["env_file"])
            # End-to-end pre-flip gate: one real ask against the shipped version,
            # in the serve container, non-empty answer required. Passport-valid
            # but unanswerable corpora (the WAL-on-:ro 502s) stop HERE, not live.
            print(f'  ask smoke ({ctx["exposed_asks"][0]}) against the new version…',
                  file=sys.stderr)
            box.verify_ask(remote, f'/data/corpus/versions/{vid}',
                           ctx["compose_dir"], ctx["env_file"],
                           ctx["exposed_asks"][0], "¿De qué trata este corpus?")
        except BoxError as e:
            print(f"verify failed, current untouched: {e}", file=sys.stderr)
            sys.exit(1)

        print("  flip current → new version; restarting serve", file=sys.stderr)
        box.run_volume_op(remote, "flip", ctx["volume"], vid)
        box.restart_serve(remote, ctx["compose_dir"], ctx["env_file"])

        print("  waiting for serve healthy (up to 120s)", file=sys.stderr)
        try:
            box.confirm_healthy(remote, timeout_s=120,
                                compose_dir=ctx["compose_dir"], env_file=ctx["env_file"])
        except BoxError:
            msg = (
                f"flip succeeded, confirm failed — current={vid}, prior retained, "
                f"run 'mo sync rollback {target_ref} {env_name}'"
            )
            print(msg, file=sys.stderr)
            sys.exit(1)

        box.run_volume_op(remote, "prune", ctx["volume"], "3")
        print(f"✓ live: {vid}", file=sys.stderr)
    finally:
        box.release_lock(remote, lockfile)


def rollback(corpus_root: Path, target_ref: str, env_name: str) -> None:
    """Flip-back tail: flip current ← previous, restart, confirm. Omits verify (corpus unchanged)."""
    remote, ctx = _resolve(corpus_root, target_ref, env_name)
    lockfile = f'{ctx["volume"]}/.sync.lock'
    box.acquire_lock(remote, lockfile, label="sync", target_ref=f"rollback {target_ref}")
    try:
        box.run_volume_op(remote, "rollback", ctx["volume"])
        box.restart_serve(remote, ctx["compose_dir"], ctx["env_file"])
        try:
            box.confirm_healthy(remote, timeout_s=120,
                                compose_dir=ctx["compose_dir"], env_file=ctx["env_file"])
        except BoxError:
            print("both current and prior failed to serve — manual intervention required",
                  file=sys.stderr)
            sys.exit(1)
    finally:
        box.release_lock(remote, lockfile)
