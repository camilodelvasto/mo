# tests/test_infra_chat_probe.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import io, urllib.error, urllib.request, pytest
from cli.infra import chat_probe
from cli.infra.chat_probe import probe_chat, ProbeError

CHECK_URL = "https://ask.moui.co/api/check"


def _resp(status, acao):
    r = io.BytesIO(b""); r.status = status
    r.headers = {"Access-Control-Allow-Origin": acao} if acao else {}
    return r

def test_match_and_204_proceeds(monkeypatch):
    monkeypatch.setattr(chat_probe.urllib.request, "urlopen",
                        lambda req, timeout=0: _resp(204, "https://g.io"))
    probe_chat(CHECK_URL, "https://g.io", "C0DE")   # no raise

def test_probe_posts_to_check_url(monkeypatch):
    """probe_chat must POST the given check URL, not /ask/find."""
    captured = []
    def fake_urlopen(req, timeout=0):
        captured.append(req.full_url)
        return _resp(204, "https://g.io")
    monkeypatch.setattr(chat_probe.urllib.request, "urlopen", fake_urlopen)
    probe_chat(CHECK_URL, "https://g.io", "C0DE")
    assert captured[0] == CHECK_URL

def test_wrong_origin_distinct_error(monkeypatch):
    monkeypatch.setattr(chat_probe.urllib.request, "urlopen",
                        lambda req, timeout=0: _resp(204, "https://other.io"))
    with pytest.raises(ProbeError, match="allows https://other.io, not"):
        probe_chat(CHECK_URL, "https://g.io", "C0DE")

def test_401_distinct_error(monkeypatch):
    def boom(req, timeout=0): raise urllib.error.HTTPError("u", 401, "Unauthorized",
                                                           {"Access-Control-Allow-Origin": "https://g.io"}, io.BytesIO(b""))
    monkeypatch.setattr(chat_probe.urllib.request, "urlopen", boom)
    with pytest.raises(ProbeError, match="rejected the .*code"):
        probe_chat(CHECK_URL, "https://g.io", "C0DE")

def test_unreachable_distinct_error(monkeypatch):
    def boom(req, timeout=0): raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(chat_probe.urllib.request, "urlopen", boom)
    with pytest.raises(ProbeError, match="could not get a usable answer"):
        probe_chat(CHECK_URL, "https://g.io", "C0DE")

def test_wildcard_flags_and_proceeds(monkeypatch, capsys):
    monkeypatch.setattr(chat_probe.urllib.request, "urlopen",
                        lambda req, timeout=0: _resp(204, "*"))
    probe_chat(CHECK_URL, "https://g.io", "C0DE")   # no raise
    assert "all origins" in capsys.readouterr().out.lower()
