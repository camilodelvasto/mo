# tests/test_sync_corpus_orchestrator.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from pathlib import Path
from cli.sync.corpus import sync, box


class FakeBox:
    def __init__(self): self.calls = []; self._current_digest = None
    def acquire_lock(self, *a, **k): self.calls.append("lock")
    def release_lock(self, *a): self.calls.append("unlock")
    def current_digest(self, r, vol): return self._current_digest
    def ship(self, *a): self.calls.append("ship")
    def ship_version(self, *a): self.calls.append("ship")
    def validate_digest(self, *a): self.calls.append("digest")
    def verify_passport(self, *a): self.calls.append("verify")
    def verify_ask(self, *a, **k): self.calls.append("ask")
    def run_volume_op(self, r, op, *a): self.calls.append(op)
    def restart_serve(self, *a): self.calls.append("restart")
    def confirm_healthy(self, *a, **k): self.calls.append("confirm")


def _patch(monkeypatch, fake, **over):
    monkeypatch.setattr(sync, "box", fake)
    monkeypatch.setattr(sync, "_resolve", lambda root, t, e: (
        {"host": "h", "user": "u"},
        {"content": "content/x", "corpus": "x",
         "compose_dir": "/opt/cs/infrastructure/corpus-server",
         "env_file": "/opt/cs/box-config/.env",
         "volume": "/opt/cs/corpus/x", "exposed_asks": ["answer"]}))
    monkeypatch.setattr(sync, "_build_local_snapshot", lambda root, env, now: (Path("/tmp/s"), "DIGEST", "VID"))
    fake._current_digest = over.get("current_digest")


def test_build_local_snapshot_reconciles_before_digest(monkeypatch, tmp_path):
    # the snapshot's index must be made current BEFORE the digest, so the box's
    # per-ask reconcile is a no-op and the :ro mount holds (the stale-index bug).
    calls = []
    monkeypatch.setattr(sync.snapshot, "build_snapshot", lambda content, dest: calls.append("build"))
    monkeypatch.setattr(sync.reconcile, "reconcile",
                        lambda corpus, root: (calls.append("reconcile"),
                                              {"embedded": 0, "dropped": 0, "refreshed": 1})[1])
    monkeypatch.setattr(sync.snapshot, "canonical_digest",
                        lambda d: (calls.append("digest"), "abc1234567890123")[1])
    monkeypatch.setattr(sync.snapshot, "version_id", lambda dg, now: f"{now}-{dg[:16]}")
    snap, digest, vid = sync._build_local_snapshot(tmp_path, {"content": str(tmp_path)}, "T")
    assert calls == ["build", "reconcile", "digest"]    # reconcile strictly before digest
    assert digest == "abc1234567890123" and vid == "T-abc1234567890123"


def test_happy_path_orders_steps_and_releases_lock(monkeypatch):
    fake = FakeBox(); _patch(monkeypatch, fake)
    sync.run(Path("/root"), "corpus-server/x", "prod", now="T")
    assert fake.calls == ["lock", "ship", "digest", "verify", "ask", "flip", "restart",
                          "confirm", "prune", "unlock"]


def test_verify_failure_leaves_current_untouched(monkeypatch):
    fake = FakeBox(); _patch(monkeypatch, fake)
    fake.verify_passport = lambda *a: (_ for _ in ()).throw(box.BoxError("local.embed unbound"))
    with pytest.raises(SystemExit):
        sync.run(Path("/root"), "corpus-server/x", "prod", now="T")
    assert "flip" not in fake.calls and "unlock" in fake.calls   # no flip; lock released


def test_idempotent_when_digest_already_current(monkeypatch):
    fake = FakeBox(); _patch(monkeypatch, fake, current_digest="DIGEST")
    sync.run(Path("/root"), "corpus-server/x", "prod", now="T")
    assert "ship" not in fake.calls and "flip" not in fake.calls and "unlock" in fake.calls


def test_confirm_timeout_is_defined_down(monkeypatch, capsys):
    fake = FakeBox(); _patch(monkeypatch, fake)
    fake.confirm_healthy = lambda *a, **k: (_ for _ in ()).throw(box.BoxError("not healthy"))
    with pytest.raises(SystemExit):
        sync.run(Path("/root"), "corpus-server/x", "prod", now="T")
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "mo sync rollback" in out and "confirm failed" in out


def test_rollback_omits_verify_keeps_confirm(monkeypatch):
    fake = FakeBox(); _patch(monkeypatch, fake)
    sync.rollback(Path("/root"), "corpus-server/x", "prod")
    assert "verify" not in fake.calls
    assert fake.calls == ["lock", "rollback", "restart", "confirm", "unlock"]


def test_rollback_confirm_failure_is_stuck_loud(monkeypatch, capsys):
    fake = FakeBox(); _patch(monkeypatch, fake)
    fake.confirm_healthy = lambda *a, **k: (_ for _ in ()).throw(box.BoxError("not healthy"))
    with pytest.raises(SystemExit):
        sync.rollback(Path("/root"), "corpus-server/x", "prod")
    err = capsys.readouterr().err
    assert "manual intervention required" in err


def test_resolve_consumes_box_layout_not_a_second_derivation(monkeypatch, tmp_path):
    from cli.sync.corpus import sync

    (tmp_path / "infrastructure").mkdir()
    (tmp_path / "infrastructure" / "remotes.yaml").write_text(
        "remotes:\n  hetzner/x:\n    host: h\n    user: u\n    path: /opt/cs\n"
        "    credential: ssh-agent\n")
    tdir = tmp_path / "infrastructure" / "targets" / "corpus-server"
    tdir.mkdir(parents=True)
    (tdir / "x.yaml").write_text(
        "stack: corpus-server\nenvironments:\n  prod:\n    remote: hetzner/x\n"
        "    corpus: cx\n    content: content/x\n    exposed_asks: [answer]\n")

    monkeypatch.setattr(sync, "box_layout",
        lambda remote: {"root": "/SENT", "compose_dir": "CD_SENT",
                        "env_file": "EF_SENT", "box_config": "BC_SENT",
                        "capabilities": "CAP_SENT"})
    monkeypatch.setattr(sync, "corpus_volume", lambda root, c: f"VOL_SENT/{c}")

    remote, ctx = sync._resolve(tmp_path, "corpus-server/x", "prod")
    assert ctx["compose_dir"] == "CD_SENT"      # from box_layout, not inlined
    assert ctx["env_file"] == "EF_SENT"
    assert ctx["volume"] == "VOL_SENT/cx"       # from corpus_volume


def test_ask_smoke_failure_leaves_current_untouched(monkeypatch):
    # the end-to-end ask is a pre-flip gate: a corpus the box cannot ANSWER from
    # must not go live (the WAL-on-:ro 502s shipped green past the passport check).
    fake = FakeBox(); _patch(monkeypatch, fake)
    fake.verify_ask = lambda *a, **k: (_ for _ in ()).throw(box.BoxError("ask died: unable to open database file"))
    with pytest.raises(SystemExit):
        sync.run(Path("/root"), "corpus-server/x", "prod", now="T")
    assert "flip" not in fake.calls and "unlock" in fake.calls
