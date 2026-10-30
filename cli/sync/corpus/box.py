# cli/sync/corpus/box.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""SSH ops against a corpus-server box. Thin wrappers over `ssh`/`tar`: build an
argv list, run with capture, raise a typed error naming stderr on non-zero. No
fallbacks."""
import json
import os
import shlex
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

from cli.sync.corpus import snapshot


class BoxError(Exception):
    pass


def _ssh_argv(remote: dict) -> list:
    # Keepalives: a converge can sit silent for 20+ minutes while the box
    # builds images; without them a NAT idle timeout drops the mapping and the
    # local ssh waits forever on a connection whose close will never arrive.
    argv = ["ssh", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=6"]
    if remote.get("ssh_key"):
        argv += ["-i", remote["ssh_key"]]
    argv.append(f'{remote["user"]}@{remote["host"]}')
    return argv


def ssh_exec(remote: dict, command: str) -> str:
    argv = _ssh_argv(remote) + [command]
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        raise BoxError(f"ssh `{command[:60]}` failed: {r.stderr.strip()}")
    return r.stdout


def ssh_stream(remote: dict, command: str, *, out=None) -> None:
    """Run a remote command whose output is PROGRESS, not data: relay it live
    through a LiveTail viewport (last 5 lines, self-erasing) instead of
    capturing until exit. Calls that parse stdout stay on ssh_exec. Non-zero
    exit raises BoxError carrying the last 30 output lines."""
    # Lazy import: keeps cli.ui off the import path of data-only consumers
    # (e.g. snapshot.py run as a script on the box, where livetail is absent).
    from cli.ui.livetail import LiveTail

    argv = _ssh_argv(remote) + [command]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            errors="replace", bufsize=1)
    tail: deque = deque(maxlen=30)
    view = LiveTail(out if out is not None else sys.stderr)
    with proc:
        try:
            for line in proc.stdout:
                tail.append(line.rstrip("\n"))
                view.add(line)
        finally:
            view.close()
    if proc.returncode != 0:
        joined = "\n".join(tail)
        raise BoxError(f"`{command[:60]}` failed on the box "
                       f"(exit {proc.returncode}); last output:\n{joined}")


def ship(remote: dict, snapshot_dir: Path, version_dir: str) -> None:
    """tar the snapshot locally and untar it into version_dir on the box."""
    remote_cmd = f'mkdir -p "{version_dir}" && tar -xzf - -C "{version_dir}"'
    # COPYFILE_DISABLE=1 stops macOS bsdtar from injecting AppleDouble `._*`
    # sidecar files into the stream — they'd land on the box but not in the local
    # snapshot, diverging the digest the box recomputes. (Linux tar ignores it.)
    tar = subprocess.Popen(["tar", "-czf", "-", "-C", str(snapshot_dir), "."],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env={**os.environ, "COPYFILE_DISABLE": "1"})
    ssh = subprocess.Popen(_ssh_argv(remote) + [remote_cmd],
                           stdin=tar.stdout, stderr=subprocess.PIPE)
    tar.stdout.close()
    _, ssh_err = ssh.communicate()
    _, tar_err = tar.communicate()
    if ssh.returncode != 0 or tar.returncode != 0:
        parts = []
        if tar_err.strip():
            parts.append(f"tar: {tar_err.decode(errors='replace').strip()}")
        if ssh_err.strip():
            parts.append(f"ssh: {ssh_err.decode(errors='replace').strip()}")
        raise BoxError(f"ship to {version_dir} failed: {'; '.join(parts) or '(no stderr)'}")


def _rsync_e(remote: dict) -> str:
    """The rsync -e transport string: ssh, plus -i <key> when the remote pins one
    (mirrors _ssh_argv's key handling)."""
    cmd = "ssh"
    if remote.get("ssh_key"):
        cmd += f' -i {remote["ssh_key"]}'
    return cmd


def _rsync_flags(link_dest: str | None) -> list:
    """Transfer flags shared by the shipper and its test. -rlt: recurse, keep
    symlinks and mtimes — mtime parity is what lets --link-dest hardlink unchanged
    files on the NEXT deploy. --link-dest points at the live version so identical
    files are hardlinked in, not re-sent; omitted on first deploy (no current yet).
    No --mkpath: the local client is openrsync, which rejects it — the caller
    pre-creates the version dir via ssh."""
    flags = ["-rlt"]
    if link_dest is not None:                    # None = first deploy; "" is never valid, not a skip
        flags.append(f"--link-dest={link_dest}/")
    return flags


def _ship_version_argv(remote: dict, snapshot_dir: Path, version_dir: str,
                       link_dest: str | None) -> list:
    return (["rsync"] + _rsync_flags(link_dest) +
            ["-e", _rsync_e(remote),
             f"{str(snapshot_dir).rstrip('/')}/",              # snapshot CONTENTS
             f'{remote["user"]}@{remote["host"]}:{version_dir}/'])


def ship_version(remote: dict, snapshot_dir: Path, version_dir: str,
                 link_dest: str | None) -> None:
    """rsync the snapshot into a fresh immutable version_dir on the box, hardlinking
    every file unchanged since link_dest (the live version) instead of re-sending it.
    version_dir stays a complete standalone tree, so validate_digest/flip/prune are
    unaffected. No fallbacks — non-zero raises BoxError naming rsync stderr."""
    ssh_exec(remote, f'mkdir -p "{version_dir}"')
    argv = _ship_version_argv(remote, snapshot_dir, version_dir, link_dest)
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        raise BoxError(f"ship to {version_dir} failed: {r.stderr.strip() or '(no stderr)'}")


_SNAPSHOT = Path(__file__).with_name("snapshot.py")


def _ssh_stdin(remote: dict, remote_cmd: str, stdin_text: str) -> str:
    r = subprocess.run(_ssh_argv(remote) + [remote_cmd], input=stdin_text,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise BoxError(f"ssh `{remote_cmd[:40]}` failed: {r.stderr.strip()}")
    return r.stdout


def ssh_python(remote: dict, script: Path, *args: str) -> str:
    """Run a local stdlib-only script ON the box via `python3 -` (script on stdin),
    args as argv. Same code on box and laptop — no shell/locale divergence."""
    import shlex
    cmd = "python3 - " + " ".join(shlex.quote(a) for a in args)
    return _ssh_stdin(remote, cmd, script.read_text())


def validate_digest(remote: dict, version_dir: str, expected: str) -> None:
    """Recompute the canonical digest of the shipped dir ON the box using the
    IDENTICAL snapshot.canonical_digest (run via ssh python3 -), not a shell
    pipeline — so framing/sort can't diverge on non-ASCII (Spanish) filenames."""
    got = ssh_python(remote, _SNAPSHOT, version_dir).strip()
    if got != expected:
        raise BoxError(f"digest mismatch in {version_dir}: box={got} expected={expected}")


_VOLUME_OP = Path(__file__).with_name("_volume_op.py")


def run_volume_op(remote: dict, op: str, volume: str, *args: str) -> None:
    """Run cli/sync/corpus/_volume_op.py on the box (same code as the local layout
    tests) via ssh_python — flip/rollback/prune/scaffold."""
    ssh_python(remote, _VOLUME_OP, op, volume, *args)


def current_digest(remote: dict, volume: str) -> str | None:
    """The 16-char digest the live `current` version dir encodes, or None if no
    current. Read off the symlink target name (`<timestamp>-<digest16>`). The
    idempotency check (Task 7) compares this to the new snapshot's digest[:16]."""
    try:
        target = ssh_exec(remote, f'readlink "{volume}/current"').strip()
    except BoxError:
        return None
    if not target:
        return None
    base = target.rsplit("/", 1)[-1]          # versions/<ts>-<digest16> -> <ts>-<digest16>
    return base.rsplit("-", 1)[-1] or None    # -> <digest16>


def verify_passport(remote: dict, version_dir_in_container: str, compose_dir: str, env_file: str) -> None:
    cmd = (f'cd "{compose_dir}" && docker compose --env-file "{env_file}" '
           f'exec -T serve mo corpus verify "{version_dir_in_container}"')
    ssh_exec(remote, cmd)   # raises BoxError(stderr naming the failing binding) on non-zero


def verify_ask(remote: dict, version_dir_in_container: str, compose_dir: str,
               env_file: str, ask_id: str, question: str) -> None:
    """The end-to-end pre-flip gate: one real ask in the serve container against
    the shipped version — index open, retrieval, and generation all on the box's
    actual medium and creds. Non-zero exit or an empty answer is a BoxError."""
    cmd = (f'cd "{compose_dir}" && docker compose --env-file "{env_file}" '
           f'exec -T serve mo corpus ask "{version_dir_in_container}" '
           f'{shlex.quote(ask_id)} {shlex.quote(question)} --json --history "[]"')
    out = ssh_exec(remote, cmd)   # raises BoxError(stderr) on non-zero
    try:
        answer = json.loads(out.strip())["answer"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise BoxError(f"ask smoke returned no parseable answer: {exc}") from exc
    if not str(answer).strip():
        raise BoxError("ask smoke returned an empty answer")


def restart_serve(remote: dict, compose_dir: str, env_file: str) -> None:
    ssh_exec(remote, f'cd "{compose_dir}" && docker compose --env-file "{env_file}" restart serve')


def compose_up(remote: dict, compose_dir: str, env_file: str) -> None:
    """Converge the stack on the box: build the images from the shipped context
    and bring the compose project up. Idempotent — an unchanged stack converges
    to the same state. Build output streams through the activity viewport (a
    rebuild can take 20 minutes; silence reads as a hang). Raises BoxError
    (tailed output) on a build/compose error."""
    ssh_stream(remote, f'cd "{compose_dir}" && docker compose '
                       f'--env-file "{env_file}" up -d --build')


def caddy_reload(remote: dict, compose_dir: str, env_file: str) -> None:
    """Make the running Caddy re-read /etc/caddy/Caddyfile. `up -d` leaves an
    unchanged caddy service running, and Caddy reads its config only at start or
    on reload. Caddy refuses a bad config and keeps serving the previous one;
    the refusal comes back as BoxError."""
    ssh_exec(remote, f'cd "{compose_dir}" && docker compose --env-file "{env_file}" '
                     f'exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile')


def prune_build_cache(remote: dict, max_used: str) -> None:
    """Bound the on-box build cache to max_used and drop dangling images. Every
    stack deploy builds gate + serve here; nothing else clears the old layers.
    --max-used-space, not --keep-storage: Docker 29 removed the latter. Image
    prune without -a leaves every tagged image, running or not."""
    ssh_exec(remote, f"docker builder prune -f --max-used-space {max_used} && "
                     f"docker image prune -f")


def confirm_healthy(remote: dict, timeout_s: int, compose_dir: str, env_file: str) -> None:
    deadline = time.monotonic() + timeout_s
    q = (f'cd "{compose_dir}" && docker compose --env-file "{env_file}" ps '
         f'--format "{{{{.Health}}}}" serve')
    while time.monotonic() < deadline:
        if ssh_exec(remote, q).strip() == "healthy":
            print(file=sys.stderr)                 # close the progress line
            return
        print(".", end="", flush=True, file=sys.stderr)   # live progress, not silent
        time.sleep(3)
    print(file=sys.stderr)
    raise BoxError(f"healthcheck not healthy within {timeout_s}s")


_LOCK_STALE_S = 1800   # a sync should never take 30 min; an older holder has crashed


def acquire_lock(remote: dict, lockfile: str, *, label: str, target_ref: str = "") -> None:
    """Atomic noclobber create storing `<epoch> <target_ref>`. `label` names the
    operation in every message ("sync", "grove deploy"). If the lock is held:
    auto-reclaim when the holder is older than _LOCK_STALE_S (a crashed holder — the
    locks.py reclaim-by-evidence posture), else fail LOUD naming the holder and the
    exact command to clear it. Never silently waits, never wedges on an orphan."""
    payload = f'$(date +%s) {target_ref}'
    try:
        ssh_exec(remote, f'set -C; echo "{payload}" > "{lockfile}"')
        return
    except BoxError:
        pass                                            # lockfile exists
    held = ssh_exec(remote, f'cat "{lockfile}" 2>/dev/null || echo 0').strip()
    now = int(ssh_exec(remote, "date +%s").strip())
    try:
        held_ts = int(held.split()[0])
    except (ValueError, IndexError):
        held_ts = 0
    if now - held_ts > _LOCK_STALE_S:                   # crashed holder → reclaim, logged
        print(f"reclaiming stale {label} lock (age {now - held_ts}s): {held}", file=sys.stderr)
        ssh_exec(remote, f'echo "{payload}" > "{lockfile}"')
        return
    raise BoxError(
        f"another {label} holds the lock ({held}); if it is stale, clear it with: "
        f'ssh {remote["user"]}@{remote["host"]} rm "{lockfile}"')


def release_lock(remote: dict, lockfile: str) -> None:
    ssh_exec(remote, f'rm -f "{lockfile}"')


def put_file(remote: dict, content: str, dest: str) -> None:
    """Write content to dest on the box via stdin (never argv — so a secret never
    appears in `ps`). Creates the parent dir, mode 600. Raises BoxError on failure."""
    import shlex
    parent = dest.rsplit("/", 1)[0]
    cmd = (f'mkdir -p {shlex.quote(parent)} && cat > {shlex.quote(dest)} '
           f'&& chmod 600 {shlex.quote(dest)}')
    _ssh_stdin(remote, cmd, content)
