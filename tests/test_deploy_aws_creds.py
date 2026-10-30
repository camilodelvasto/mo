# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from cli.deploy import aws_creds
from cli.deploy.aws_creds import resolve_aws_creds, AwsCredsError


def test_resolve_formats_a_credentials_file(monkeypatch):
    monkeypatch.setattr(aws_creds, "_export", lambda profile:
        "AWS_ACCESS_KEY_ID=AKIATEST\nAWS_SECRET_ACCESS_KEY=shh\n")
    out = resolve_aws_creds("bedrock-claude-eu")
    assert "[default]" in out
    assert "aws_access_key_id = AKIATEST" in out
    assert "aws_secret_access_key = shh" in out
    assert "aws_session_token" not in out              # static key → no token line


def test_resolve_includes_session_token_when_present(monkeypatch):
    monkeypatch.setattr(aws_creds, "_export", lambda profile:
        "AWS_ACCESS_KEY_ID=AKIA\nAWS_SECRET_ACCESS_KEY=s\nAWS_SESSION_TOKEN=tok\n")
    out = resolve_aws_creds("p")
    assert "aws_session_token = tok" in out            # same code path for SSO


def test_resolve_unknown_profile_fails_loud(monkeypatch):
    def boom(profile):
        raise aws_creds.AwsCredsError("profile 'nope' not found")
    monkeypatch.setattr(aws_creds, "_export", boom)
    with pytest.raises(AwsCredsError, match="nope"):
        resolve_aws_creds("nope")
