# tests/test_sync_corpus_box.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import io
import subprocess, pytest
from cli.sync.corpus import box


def test_ssh_exec_builds_argv_and_raises_on_error(monkeypatch):
    seen = {}
    class R: returncode = 0; stdout = "ok"; stderr = ""
    def fake_run(cmd, **kw): seen["cmd"] = cmd; return R()
    monkeypatch.setattr(subprocess, "run", fake_run)
    out = box.ssh_exec({"host": "h", "user": "u"}, "echo hi")
    assert seen["cmd"][:3] == ["ssh", "u@h", "echo hi"] or seen["cmd"][0] == "ssh"
    assert "u@h" in seen["cmd"] and "echo hi" in seen["cmd"]
    assert out == "ok"


def test_ssh_exec_raises_named_on_nonzero(monkeypatch):
    class R: returncode = 1; stdout = ""; stderr = "boom"
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: R())
    with pytest.raises(box.BoxError, match="boom"):
        box.ssh_exec({"host": "h", "user": "u"}, "false")


def test_ssh_exec_includes_key_when_present(monkeypatch):
    seen = {}
    class R: returncode = 0; stdout = ""; stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd) or R())
    box.ssh_exec({"host": "h", "user": "u", "ssh_key": "/k"}, "x")
    assert "-i" in seen["cmd"] and "/k" in seen["cmd"]


def test_confirm_healthy_polls_until_healthy(monkeypatch):
    from cli.sync.corpus import box
    states = iter(["starting", "starting", "healthy"])
    seen_cmd = {}
    def fake_ssh(r, c):
        seen_cmd["cmd"] = c
        return next(states)
    monkeypatch.setattr(box, "ssh_exec", fake_ssh)
    monkeypatch.setattr(box.time, "sleep", lambda s: None)
    box.confirm_healthy({"host": "h", "user": "u"}, timeout_s=10,
                        compose_dir="/opt/cs/infrastructure/corpus-server",
                        env_file="/opt/cs/box-config/.env")
    assert '--env-file "/opt/cs/box-config/.env"' in seen_cmd["cmd"]


def test_confirm_healthy_times_out(monkeypatch):
    from cli.sync.corpus import box
    import time
    monkeypatch.setattr(box, "ssh_exec", lambda r, c: "starting")
    monkeypatch.setattr(box.time, "sleep", lambda s: None)
    mono = iter([0, 0, 99])
    monkeypatch.setattr(box.time, "monotonic", lambda: next(mono))
    with pytest.raises(box.BoxError, match="not healthy"):
        box.confirm_healthy({"host": "h", "user": "u"}, timeout_s=2,
                            compose_dir="/opt/cs/infrastructure/corpus-server",
                            env_file="/opt/cs/box-config/.env")


def _lock_fake(create_fails: bool, held_line: str, now: int):
    def fake(remote, cmd):
        if cmd.startswith("set -C"):
            if create_fails: raise box.BoxError("File exists")
            return ""
        if cmd.startswith("cat "): return held_line
        if cmd == "date +%s": return str(now)
        return ""                                    # overwrite / rm
    return fake


def test_acquire_lock_fails_loud_when_held_recent(monkeypatch):
    monkeypatch.setattr(box, "ssh_exec", _lock_fake(True, "1000 corpus-server/x", now=1100))
    with pytest.raises(box.BoxError, match="another sync holds the lock"):
        box.acquire_lock({"host": "h", "user": "u"}, "/vol/.sync.lock", label="sync")


def test_acquire_lock_reclaims_when_stale(monkeypatch, capsys):
    monkeypatch.setattr(box, "ssh_exec", _lock_fake(True, "1000 corpus-server/x", now=5000))
    box.acquire_lock({"host": "h", "user": "u"}, "/vol/.sync.lock", label="sync")   # no raise
    assert "reclaiming stale sync lock" in capsys.readouterr().err


def test_acquire_lock_messages_carry_the_label(monkeypatch, capsys):
    monkeypatch.setattr(box, "ssh_exec", _lock_fake(True, "1000 /es", now=1100))
    with pytest.raises(box.BoxError, match="another grove deploy holds the lock") as exc:
        box.acquire_lock({"host": "h", "user": "u"}, "/s/x.lock", label="grove deploy")
    assert "sync" not in str(exc.value)
    monkeypatch.setattr(box, "ssh_exec", _lock_fake(True, "1000 /es", now=5000))
    box.acquire_lock({"host": "h", "user": "u"}, "/s/x.lock", label="grove deploy")
    assert "reclaiming stale grove deploy lock" in capsys.readouterr().err


def test_acquire_lock_requires_a_label():
    with pytest.raises(TypeError, match="label"):
        box.acquire_lock({"host": "h", "user": "u"}, "/s/x.lock")


def test_acquire_lock_succeeds_when_free(monkeypatch):
    monkeypatch.setattr(box, "ssh_exec", _lock_fake(False, "", now=0))
    box.acquire_lock({"host": "h", "user": "u"}, "/vol/.sync.lock", label="sync")   # no raise


def test_current_digest_reads_symlink_suffix(monkeypatch):
    monkeypatch.setattr(box, "ssh_exec", lambda r, c: "versions/20260621-120000-abcdef0123456789")
    assert box.current_digest({"host": "h", "user": "u"}, "/vol") == "abcdef0123456789"


def test_current_digest_none_when_absent(monkeypatch):
    monkeypatch.setattr(box, "ssh_exec",
                        lambda r, c: (_ for _ in ()).throw(box.BoxError("No such file")))
    assert box.current_digest({"host": "h", "user": "u"}, "/vol") is None


def test_verify_passport_uses_abs_env_file(monkeypatch):
    seen = {}
    monkeypatch.setattr(box, "ssh_exec", lambda r, c: seen.update(cmd=c) or "")
    box.verify_passport({"host": "h", "user": "u"},
                        "/data/corpus/versions/VID",
                        "/opt/cs/infrastructure/corpus-server",
                        "/opt/cs/box-config/.env")
    assert '--env-file "/opt/cs/box-config/.env"' in seen["cmd"]
    assert 'cd "/opt/cs/infrastructure/corpus-server"' in seen["cmd"]


def test_restart_serve_uses_abs_env_file(monkeypatch):
    seen = {}
    monkeypatch.setattr(box, "ssh_exec", lambda r, c: seen.update(cmd=c) or "")
    box.restart_serve({"host": "h", "user": "u"},
                      "/opt/cs/infrastructure/corpus-server",
                      "/opt/cs/box-config/.env")
    assert '--env-file "/opt/cs/box-config/.env"' in seen["cmd"]
    assert 'cd "/opt/cs/infrastructure/corpus-server"' in seen["cmd"]


def test_compose_up_runs_build_in_compose_dir(monkeypatch):
    from cli.sync.corpus import box
    seen = {}
    monkeypatch.setattr(box, "ssh_stream",
                        lambda remote, cmd, **k: seen.setdefault("cmd", cmd))
    box.compose_up({"host": "h", "user": "u"},
                   "/opt/corpus-server/infrastructure/corpus-server",
                   "/opt/corpus-server/box-config/.env")
    assert 'cd "/opt/corpus-server/infrastructure/corpus-server"' in seen["cmd"]
    assert '--env-file "/opt/corpus-server/box-config/.env"' in seen["cmd"]
    assert "up -d --build" in seen["cmd"]


def test_box_digest_runner_matches_canonical(tmp_path):
    """snapshot.py run as a script (the box path) must equal canonical_digest in
    process — including a non-ASCII + spaced filename (the Spanish corpus has them).
    Guaranteed by same-code, this test pins it so a future refactor can't break it."""
    import subprocess
    from pathlib import Path
    from cli.sync.corpus import snapshot
    d = tmp_path / "v"; (d / "sub").mkdir(parents=True)
    (d / "corpus.yaml").write_bytes(b"id: c\n")
    (d / "sub" / "informe ñoño.md").write_bytes("acción".encode())   # non-ASCII + space
    (d / "índice.txt").write_bytes(b"x")
    expected = snapshot.canonical_digest(d)
    r = subprocess.run(["python3", str(Path(snapshot.__file__)), str(d)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected


def test_ship_disables_macos_appledouble(monkeypatch, tmp_path):
    import io
    from cli.sync.corpus import box
    seen = []

    class FakeProc:
        def __init__(self, *a, **k):
            seen.append((a, k))
            self.stdout = io.BytesIO(b"")
            self.returncode = 0
        def communicate(self): return (b"", b"")

    monkeypatch.setattr(box.subprocess, "Popen", FakeProc)
    box.ship({"host": "h", "user": "u"}, tmp_path, "/v")
    tar_kwargs = seen[0][1]                      # first Popen is the tar process
    assert tar_kwargs.get("env", {}).get("COPYFILE_DISABLE") == "1"


def test_put_file_writes_content_via_stdin_not_argv(monkeypatch):
    from cli.sync.corpus import box
    seen = {}
    def fake_stdin(remote, cmd, text):
        seen["cmd"] = cmd; seen["text"] = text; return ""
    monkeypatch.setattr(box, "_ssh_stdin", fake_stdin)
    box.put_file({"host": "h", "user": "u"}, "secret-bytes", "/opt/cs/secrets/aws")
    assert "secret-bytes" not in seen["cmd"]           # secret never in the command/argv
    assert seen["text"] == "secret-bytes"              # it rode stdin
    assert "mkdir -p /opt/cs/secrets" in seen["cmd"]
    assert "/opt/cs/secrets/aws" in seen["cmd"]
    assert "chmod 600" in seen["cmd"]


def test_put_file_quotes_paths_with_shell_specials(monkeypatch):
    from cli.sync.corpus import box
    import shlex
    seen = {}
    def fake_stdin(remote, cmd, text):
        seen["cmd"] = cmd; return ""
    monkeypatch.setattr(box, "_ssh_stdin", fake_stdin)
    dest = "/opt/cs/secrets/$x `y`/aws"
    box.put_file({"host": "h", "user": "u"}, "content", dest)
    quoted_dest = shlex.quote(dest)
    # Verify the path is quoted in the command (shlex.quote wraps with single quotes)
    assert quoted_dest in seen["cmd"]
    # The quoted form is shell-safe: shlex.quote on a path with $ and backticks
    # produces a single-quoted string where no expansion happens
    assert "'" in quoted_dest


def test_ship_version_argv_has_flags_transport_and_endpoints(tmp_path):
    from cli.sync.corpus import box
    argv = box._ship_version_argv(
        {"host": "h", "user": "u"}, tmp_path, "/vol/versions/VID", "/vol/current")
    assert argv[0] == "rsync"
    assert "-rlt" in argv
    assert "--link-dest=/vol/current/" in argv
    assert argv[argv.index("-e") + 1] == "ssh"                 # transport, no key
    assert argv[-2] == f"{str(tmp_path)}/"                      # snapshot CONTENTS
    assert argv[-1] == "u@h:/vol/versions/VID/"                 # remote version dir


def test_ship_version_argv_includes_ssh_key(tmp_path):
    from cli.sync.corpus import box
    argv = box._ship_version_argv(
        {"host": "h", "user": "u", "ssh_key": "/k"}, tmp_path, "/vol/versions/VID", "/vol/current")
    assert argv[argv.index("-e") + 1] == "ssh -i /k"


def test_ship_version_argv_omits_linkdest_on_first_deploy(tmp_path):
    from cli.sync.corpus import box
    argv = box._ship_version_argv(
        {"host": "h", "user": "u"}, tmp_path, "/vol/versions/VID", None)
    assert not any(a.startswith("--link-dest") for a in argv)


def test_ship_version_mkdirs_then_runs_rsync(monkeypatch, tmp_path):
    from cli.sync.corpus import box
    seen = {"ssh": [], "run": None}
    monkeypatch.setattr(box, "ssh_exec", lambda r, c: seen["ssh"].append(c) or "")
    class R: returncode = 0; stdout = ""; stderr = ""
    monkeypatch.setattr(box.subprocess, "run",
                        lambda argv, **k: seen.update(run=(argv, k)) or R())
    box.ship_version({"host": "h", "user": "u"}, tmp_path, "/vol/versions/VID", "/vol/current")
    assert any('mkdir -p "/vol/versions/VID"' in c for c in seen["ssh"])   # dir pre-created
    assert seen["run"][0][0] == "rsync"
    assert seen["run"][1].get("capture_output") is True and seen["run"][1].get("text") is True


def test_ship_version_raises_named_on_nonzero(monkeypatch, tmp_path):
    from cli.sync.corpus import box
    monkeypatch.setattr(box, "ssh_exec", lambda r, c: "")
    class R: returncode = 23; stdout = ""; stderr = "rsync: link_dest boom"
    monkeypatch.setattr(box.subprocess, "run", lambda argv, **k: R())
    with pytest.raises(box.BoxError, match="boom"):
        box.ship_version({"host": "h", "user": "u"}, tmp_path, "/vol/versions/VID", "/vol/current")


def test_link_dest_hardlinks_unchanged_and_preserves_digest(tmp_path):
    """The point of the feature: with --link-dest at the prior version, rsync
    hardlinks unchanged files (no transfer) and the shipped tree is byte-identical
    (same canonical_digest). Real local rsync, no ssh; the flags come from the
    shipper so the test can't drift from production."""
    import os, shutil, subprocess
    from cli.sync.corpus import box, snapshot

    # v1 snapshot: a stable content-addressed doc + an index
    src = tmp_path / "snap1"
    (src / "corpus" / "aa").mkdir(parents=True)
    (src / "corpus.yaml").write_bytes(b"id: c\n")
    (src / "corpus" / "aa" / "doc.pdf").write_bytes(b"PDF-BYTES" * 1000)
    (src / "index").mkdir()
    (src / "index" / "corpus.db").write_bytes(b"INDEX-V1")

    prev = tmp_path / "versions" / "v1"
    prev.mkdir(parents=True)                                   # ship pre-creates the dir
    subprocess.run(["rsync", *box._rsync_flags(None), f"{src}/", f"{prev}/"], check=True)
    assert snapshot.canonical_digest(prev) == snapshot.canonical_digest(src)

    # v2: identical doc, only the index changes
    src2 = tmp_path / "snap2"
    shutil.copytree(src, src2)
    (src2 / "index" / "corpus.db").write_bytes(b"INDEX-V2-longer")

    dest = tmp_path / "versions" / "v2"
    dest.mkdir(parents=True)
    subprocess.run(["rsync", *box._rsync_flags(str(prev)), f"{src2}/", f"{dest}/"], check=True)

    # correctness: shipped tree equals the local snapshot exactly
    assert snapshot.canonical_digest(dest) == snapshot.canonical_digest(src2)
    # optimization: unchanged doc was hardlinked from prev (same inode → zero bytes sent)
    assert (dest / "corpus" / "aa" / "doc.pdf").stat().st_ino == \
           (prev / "corpus" / "aa" / "doc.pdf").stat().st_ino
    # changed index is a fresh file, not a link to the old one
    assert (dest / "index" / "corpus.db").stat().st_ino != \
           (prev / "index" / "corpus.db").stat().st_ino
    assert (dest / "index" / "corpus.db").read_bytes() == b"INDEX-V2-longer"


def test_ssh_argv_keeps_long_silent_connections_alive():
    """A 20-minute silent docker build must survive NAT idle timeouts — without
    keepalives the local ssh waits forever on a connection the router dropped."""
    from cli.sync.corpus.box import _ssh_argv
    argv = _ssh_argv({"user": "root", "host": "box"})
    joined = " ".join(argv)
    assert "ServerAliveInterval" in joined and "ServerAliveCountMax" in joined


def _local_argv(remote):
    """The ssh_stream test seam: run the command locally instead of over ssh —
    the real Popen/pipe/line path is exercised, no network, no fake ssh."""
    return ["bash", "-c"]


def test_ssh_stream_relays_lines_in_order(monkeypatch):
    import io
    from cli.sync.corpus import box as boxmod
    monkeypatch.setattr(boxmod, "_ssh_argv", _local_argv)
    out = io.StringIO()                              # non-TTY → passthrough
    boxmod.ssh_stream({"user": "u", "host": "h"},
                      "echo uno; echo dos 1>&2; echo tres", out=out)
    body = out.getvalue()
    assert body.index("uno") < body.index("tres")
    assert "dos" in body                             # stderr merged into stream


def test_ssh_stream_failure_raises_boxerror_with_tail(monkeypatch):
    import io
    import pytest
    from cli.sync.corpus import box as boxmod
    monkeypatch.setattr(boxmod, "_ssh_argv", _local_argv)
    out = io.StringIO()
    with pytest.raises(boxmod.BoxError) as e:
        boxmod.ssh_stream({"user": "u", "host": "h"},
                          "echo building; echo BOOM; exit 7", out=out)
    assert "BOOM" in str(e.value)                    # the tail rides the error
    assert "exit 7" in str(e.value)                  # and the exit code is named


def test_compose_up_streams_instead_of_capturing(monkeypatch):
    from cli.sync.corpus import box as boxmod
    calls = {}
    monkeypatch.setattr(boxmod, "ssh_stream",
                        lambda remote, cmd, **k: calls.setdefault("cmd", cmd))
    monkeypatch.setattr(boxmod, "ssh_exec",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must stream")))
    boxmod.compose_up({"user": "u", "host": "h"}, "/opt/cs", "/opt/env")
    assert "docker compose" in calls["cmd"] and "up -d --build" in calls["cmd"]


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_ssh_stream_tty_erases_viewport_on_success(monkeypatch):
    from cli.sync.corpus import box as boxmod
    monkeypatch.setattr(boxmod, "_ssh_argv", _local_argv)
    tty = _Tty()
    boxmod.ssh_stream({"user": "u", "host": "h"}, "echo uno; echo dos", out=tty)
    # cursor-up over the rendered lines + erase-below: viewport self-erases on success
    assert tty.getvalue().endswith("\x1b[2F\x1b[0J")


def test_ssh_stream_tty_erases_viewport_on_failure(monkeypatch):
    from cli.sync.corpus import box as boxmod
    monkeypatch.setattr(boxmod, "_ssh_argv", _local_argv)
    tty = _Tty()
    with pytest.raises(boxmod.BoxError):
        boxmod.ssh_stream({"user": "u", "host": "h"}, "echo x; exit 3", out=tty)
    # viewport must be erased even on failure (erase-below sequence present)
    assert "\x1b[0J" in tty.getvalue()
