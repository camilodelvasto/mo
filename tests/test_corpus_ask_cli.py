import json

import pytest

from shapes.corpus.commands._access_cli import parse_query_args, error_kind
from shapes.corpus.access.errors import (AskError, CitationError, FilterError,
                                         SynthesisError, TitleError)
from tests.test_corpus_access_run_ask import _machine, _corpus, FIND_ASK


def test_parse_history_flag_json():
    q, opts = parse_query_args(["hello", "--history", '[{"role":"user","content":"hi"}]'])
    assert q == "hello"
    assert opts["history"] == [{"role": "user", "content": "hi"}]


def test_parse_history_from_file(tmp_path):
    f = tmp_path / "hist.json"
    f.write_text('[{"role":"user","content":"hi"}]')
    q, opts = parse_query_args(["hello", "--history", f"@{f}"])
    assert opts["history"] == [{"role": "user", "content": "hi"}]


def test_parse_history_missing_file_is_clean_error(tmp_path):
    with pytest.raises(SystemExit, match="not readable"):
        parse_query_args(["q", "--history", f"@{tmp_path/'nope.json'}"])


def test_parse_history_rejects_nonjson():
    with pytest.raises(SystemExit):
        parse_query_args(["q", "--history", "not json"])


def test_parse_history_rejects_non_list():
    with pytest.raises(SystemExit):
        parse_query_args(["q", "--history", "{}"])


def test_parse_history_rejects_malformed_turn():
    with pytest.raises(SystemExit, match="role"):
        parse_query_args(["q", "--history", '[{"role":"user"}]'])     # missing content


def test_error_kind_mapping():
    assert error_kind(CitationError("x")) == "citation_check"
    assert error_kind(SynthesisError("x")) == "synthesis_failed"
    assert error_kind(AskError("no ask named 'nope'")) == "unknown_ask"
    assert error_kind(FilterError("bad where")) == "engine_error"
    # a malformed/empty title is a synthesis failure, not an unknown ask (would be 404)
    assert error_kind(TitleError("empty title")) == "synthesis_failed"
    # parity with _stream_error_kind: the same fault carries the same kind on
    # either path — a misbinding is the box's fault, a bad history the request's.
    from shapes.corpus.access.errors import HistoryError
    from shapes.corpus.engine.errors import CapabilityError
    assert error_kind(HistoryError("ends on a user turn")) == "history_malformed"
    assert error_kind(CapabilityError("reads: envelope")) == "capability_binding"


def test_ask_cli_json_error_envelope_unknown_ask(tmp_path, capsys):
    from shapes.corpus.commands import ask as ask_cmd
    machine = _machine(tmp_path, "unused")
    corpus = _corpus(tmp_path, FIND_ASK)
    with pytest.raises(SystemExit) as e:
        ask_cmd.run(machine, "corpus", [str(corpus), "nope", "q", "--json"])
    assert e.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["kind"] == "unknown_ask"
    assert "nope" in out["error"]["detail"]


def test_find_rejects_history(tmp_path):
    from shapes.corpus.commands import find as find_cmd
    machine = _machine(tmp_path, "unused")
    corpus = _corpus(tmp_path, FIND_ASK)
    with pytest.raises(SystemExit, match="history"):
        find_cmd.run(machine, "corpus", [str(corpus), "q", "--history", "[]"])
