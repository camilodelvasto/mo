# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import json
from shapes.corpus.commands import ask as ask_cmd
from shapes.corpus.access import run_ask


def test_stream_flag_prints_ndjson(monkeypatch, capsys, tmp_path):
    events = [{"event": "step", "text": "Buscando…"},
              {"event": "token", "text": "hi"},
              {"event": "done", "model": "m", "usage": {}, "cost_usd": 0.0}]
    monkeypatch.setattr(ask_cmd, "resolve_corpus", lambda args: tmp_path)
    monkeypatch.setattr(run_ask, "run_ask_stream",
                        lambda *a, **k: iter(events))
    # args[0] = corpus path, args[1] = ask_id, args[2:] = parse_query_args input
    ask_cmd.run(tmp_path, "inst", [str(tmp_path), "myask", "q", "--stream"])
    out = capsys.readouterr().out
    lines = [json.loads(l) for l in out.splitlines() if l.strip()]
    assert [e["event"] for e in lines] == ["step", "token", "done"]


def test_stream_error_event_exits_1(monkeypatch, capsys, tmp_path):
    events = [{"event": "step", "text": "Buscando…"},
              {"event": "error", "detail": "engine blew up"}]
    monkeypatch.setattr(ask_cmd, "resolve_corpus", lambda args: tmp_path)
    monkeypatch.setattr(run_ask, "run_ask_stream",
                        lambda *a, **k: iter(events))
    import pytest
    with pytest.raises(SystemExit) as exc_info:
        ask_cmd.run(tmp_path, "inst", [str(tmp_path), "myask", "q", "--stream"])
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    lines = [json.loads(l) for l in out.splitlines() if l.strip()]
    assert lines[0]["event"] == "step"
    assert lines[1]["event"] == "error"
