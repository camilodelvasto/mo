# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Resolve-once proven AT THE READ: a flip under a live serve must not change a
grounded record (the retrieved chunk text) until restart. Boots a real serve
subprocess against a two-version volume; retrieve-only `search` ask, no LLM."""
import json, os, shutil, signal, socket, sqlite3, subprocess, sys, time, urllib.request
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "corpus-server-fixture"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="needs the corpus-server fixture")
SEARCH_ASK = "search"          # the fixture's retrieve-only ask id (confirmed: ask.yaml line 24)
SEARCH_TERM = "photosynthesis"  # present in corpus.db chunk rowid=1


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _make_version(dest: Path, marker: str | None):
    shutil.copytree(FIXTURE, dest, dirs_exist_ok=True)
    shutil.rmtree(dest / "derived", ignore_errors=True)         # runtime, not data
    if marker:                                                  # tag a chunk so v2 differs
        con = sqlite3.connect(dest / "index" / "corpus.db")
        rid, text = con.execute("SELECT rowid, text FROM chunks ORDER BY rowid LIMIT 1").fetchone()
        con.execute("UPDATE chunks SET text=? WHERE rowid=?", (f"{marker} {text}", rid))
        con.execute("UPDATE fts_chunks SET text=? WHERE rowid=?", (f"{marker} {text}", rid))
        con.commit(); con.close()


def _post_passages(port, ask, question):
    """Return the passages list from an ask response. Provenance (timing) is
    excluded so the comparison is grounded on the retrieved chunk text only."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/ask/{ask}",
        data=json.dumps({"question": question, "history": []}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.loads(r.read().decode())
    return payload["passages"]


def _serve(volume, port):
    # cwd=ROOT so find_corpus_root resolves the project (capabilities, shapes);
    # the served corpus is the volume's `current` symlink.
    p = subprocess.Popen([sys.executable, "-m", "cli.moui", "corpus", "serve",
                          str(volume / "current"), "--port", str(port), "--host", "127.0.0.1"],
                         cwd=ROOT)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=1); return p
        except Exception:
            time.sleep(0.5)
    p.kill(); raise RuntimeError("serve did not come up")


def test_flip_under_live_serve_holds_until_restart(tmp_path):
    from cli.sync.corpus import _volume_op as vop
    vol = tmp_path / "vol"; (vol / "versions").mkdir(parents=True)
    _make_version(vol / "versions" / "v1", marker=None)
    _make_version(vol / "versions" / "v2", marker="BETAMARKER")
    os.symlink("versions/v1", vol / "current")
    port = _free_port(); p = _serve(vol, port)
    try:
        before = _post_passages(port, SEARCH_ASK, SEARCH_TERM)   # chunk texts from v1
        vop.flip(vol, "v2")                                       # flip under the LIVE serve
        during = _post_passages(port, SEARCH_ASK, SEARCH_TERM)
        assert during == before, "resolve-once broken: flip changed the served record"
    finally:
        p.send_signal(signal.SIGINT); p.wait(timeout=10)
    port2 = _free_port(); p2 = _serve(vol, port2)                 # restart re-resolves -> v2
    try:
        after = _post_passages(port2, SEARCH_ASK, SEARCH_TERM)
        assert after != before, "restart did not pick up the flipped version"
    finally:
        p2.send_signal(signal.SIGINT); p2.wait(timeout=10)
