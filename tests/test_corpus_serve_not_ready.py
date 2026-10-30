# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
from fastapi.testclient import TestClient
from shapes.corpus.service.app import create_not_ready_app


def test_not_ready_app_503s_on_ask():
    app = create_not_ready_app("no current symlink")
    c = TestClient(app)
    r = c.post("/ask/find", json={"question": "x", "history": []})
    assert r.status_code == 503
    assert "corpus not ready" in r.json()["detail"]


def test_not_ready_app_503s_any_ask_name():
    c = TestClient(create_not_ready_app("x"))
    assert c.post("/ask/answer", json={"question": "q", "history": []}).status_code == 503
