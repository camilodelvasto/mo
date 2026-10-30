from shapes.corpus.engine.observer import ConsoleObserver


def test_level0_prints_failed_but_not_stage_done(capsys):
    obs = ConsoleObserver(level=0)
    obs.emit("stage-done", doc_id="abcd1234ef", stage="chunk",
             capability="engine.chunk-ast", locality="local", duration_ms=3)
    obs.emit("failed", doc_id="abcd1234ef", stage="normalize", reason="boom")
    err = capsys.readouterr().err
    assert err.startswith("FAILED")                         # nothing before FAILED
    assert "FAILED abcd1234 at stage normalize: boom" in err


def test_level1_prints_stage_done_aligned(capsys):
    ConsoleObserver(level=1).emit(
        "stage-done", doc_id="abcd1234ef", stage="normalize",
        capability="local.markitdown", locality="local", duration_ms=1200)
    err = capsys.readouterr().err
    assert "stage" in err and "abcd1234" in err and "normalize" in err
    assert "local.markitdown" in err and "1.2s" in err


def test_llm_summary_shows_confidence_and_park(capsys):
    ConsoleObserver(level=1).emit(
        "llm-call", doc_id="abcd1234ef", stage="characterize",
        capability="api.claude", duration_ms=3400,
        fields={"tipo": "informe"}, confidence={"tipo": 0.91, "aud": 0.6},
        parked=["aud"], gates={"tipo": 0.8, "aud": 0.8},
        prompt="PROMPT TEXT", response="RESP TEXT")
    err = capsys.readouterr().err
    assert "llm" in err and "api.claude" in err and "3.4s" in err
    assert "tipo=informe(0.91)" in err
    assert "aud(0.60<0.80)" in err          # parked field with conf < gate
    assert "PROMPT TEXT" not in err          # level 1 hides the full text


def test_llm_level2_includes_prompt_and_response(capsys):
    ConsoleObserver(level=2).emit(
        "llm-call", doc_id="abcd1234ef", stage="characterize",
        capability="api.claude", duration_ms=10, fields={}, confidence={},
        parked=[], gates={}, prompt="PROMPT TEXT", response="RESP TEXT")
    err = capsys.readouterr().err
    assert "PROMPT TEXT" in err and "RESP TEXT" in err


def test_stage_done_with_no_duration_shows_em_dash(capsys):
    ConsoleObserver(level=1).emit(
        "stage-done", doc_id="abcd1234ef", stage="stamp",
        capability="engine.stamp", locality="local", duration_ms=None)
    err = capsys.readouterr().err
    assert "stamp" in err and "—" in err


def test_level0_always_on_events_render(capsys):
    obs = ConsoleObserver(level=0)
    obs.emit("quarantined", doc_id="abcd1234ef", stage="anonymize")
    obs.emit("halted", doc_id="abcd1234ef", reason="custody chain broke")
    obs.emit("orphan", target="bundle-x", detail="no sidecar")
    err = capsys.readouterr().err
    assert "QUARANTINED abcd1234 at stage anonymize" in err
    assert "HALTED abcd1234: custody chain broke" in err
    assert "ORPHAN bundle-x: no sidecar" in err


def test_level1_complete_and_retired(capsys):
    obs = ConsoleObserver(level=1)
    obs.emit("complete", doc_id="abcd1234ef")
    obs.emit("retired", doc_id="abcd1234ef", rule="fields.consent == declined")
    err = capsys.readouterr().err
    assert "done      abcd1234" in err
    assert "retire    abcd1234  (fields.consent == declined)" in err
