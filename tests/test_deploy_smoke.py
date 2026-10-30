# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from cli.deploy import smoke
from cli.deploy.smoke import smoke_models, SmokeError, model_region_pairs

_CAPS = {"capabilities": {
    "api.claude": {"run": ["/app/bin/claude-bedrock", "--model", "haiku", "--region", "eu-central-1", "--max-tokens", "1024"]},
    "api.claude-json": {"run": ["/app/bin/claude-bedrock-json", "--model", "opus", "--region", "eu-central-1", "--max-tokens", "2048"]},
}}


def test_model_region_pairs_parses_distinct():
    assert model_region_pairs(_CAPS) == {("haiku", "eu-central-1"), ("opus", "eu-central-1")}


def test_smoke_passes_when_every_model_invokes(monkeypatch):
    called = []
    monkeypatch.setattr(smoke, "_converse_1tok",
                        lambda profile, model, region: called.append(model))
    smoke_models("bedrock-claude-eu", _CAPS)
    assert set(called) == {"haiku", "opus"}            # every configured model probed


def test_smoke_fails_loud_naming_the_model(monkeypatch):
    def boom(profile, model, region):
        if model == "opus":
            raise smoke.SmokeError("AccessDenied: model access not granted")
    monkeypatch.setattr(smoke, "_converse_1tok", boom)
    with pytest.raises(SmokeError, match="opus"):
        smoke_models("bedrock-claude-eu", _CAPS)
