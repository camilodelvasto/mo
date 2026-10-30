# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import importlib
import pytest
from shapes.corpus.access.errors import PassportError

verify_cmd = importlib.import_module("shapes.corpus.commands.verify_cmd")


def test_verify_calls_passport_with_lexical_flag(tmp_path, monkeypatch):
    # an embedded corpus (declared embedder) → verify(..., lexical=False)
    corpus = tmp_path / "c"; (corpus / "index").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    calls = {}
    monkeypatch.setattr(verify_cmd, "resolve_corpus", lambda args: corpus)
    monkeypatch.setattr(verify_cmd, "declared_embedder", lambda c: "local.embed")
    monkeypatch.setattr(verify_cmd, "passport",
                        type("P", (), {"verify": staticmethod(
                            lambda c, root, *, lexical: calls.update(lexical=lexical) or
                            {"capability": "local.embed", "model": "bge-m3", "dimension": 1024})}))
    verify_cmd.run(tmp_path, "corpus", [str(corpus)])
    assert calls["lexical"] is False


def test_verify_propagates_passport_error(tmp_path, monkeypatch):
    corpus = tmp_path / "c"; corpus.mkdir()
    monkeypatch.setattr(verify_cmd, "resolve_corpus", lambda args: corpus)
    monkeypatch.setattr(verify_cmd, "declared_embedder", lambda c: "local.embed")
    def boom(c, root, *, lexical): raise PassportError("embedder model diverged")
    monkeypatch.setattr(verify_cmd, "passport", type("P", (), {"verify": staticmethod(boom)}))
    with pytest.raises(PassportError, match="diverged"):
        verify_cmd.run(tmp_path, "corpus", [str(corpus)])
