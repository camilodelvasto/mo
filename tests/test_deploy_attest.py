# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The deploy gate for attachments: a box whose exposed asks accept images must
declare where its signing secret lives, and that secret must be real. Otherwise the
stack ships and every upload 500s at /verify — a runtime discovery of a deploy-time
fact. Pure rail rules, checked before the box is touched."""
import pytest
from pathlib import Path
from cli.deploy.stack import resolve_attest_secret

ATT = {"asks": [{"id": "mira", "attachments": {"accept": ["image"]},
                 "synthesize": {"uses": "api.claude-vision", "prompt": "p"}}]}
PLAIN = {"asks": [{"id": "plain", "synthesize": {"uses": "api.claude-json", "prompt": "p"}}]}


def test_attachments_box_without_a_declared_secret_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="attest_secret"):
        resolve_attest_secret(tmp_path, {"exposed_asks": ["mira"]}, ATT)


def test_declared_secret_that_is_missing_is_refused(tmp_path):
    env = {"exposed_asks": ["mira"], "attest_secret": "secrets/cs/attest.secret"}
    with pytest.raises(SystemExit, match="secrets/cs/attest.secret"):
        resolve_attest_secret(tmp_path, env, ATT)


def test_declared_secret_that_is_empty_is_refused(tmp_path):
    (tmp_path / "s.secret").write_text("   \n")
    env = {"exposed_asks": ["mira"], "attest_secret": "s.secret"}
    with pytest.raises(SystemExit, match="empty"):
        resolve_attest_secret(tmp_path, env, ATT)


def test_declared_secret_is_read_and_stripped(tmp_path):
    (tmp_path / "s.secret").write_text("d34db33f\n")
    env = {"exposed_asks": ["mira"], "attest_secret": "s.secret"}
    assert resolve_attest_secret(tmp_path, env, ATT) == "d34db33f"


def test_a_box_without_attachments_needs_no_secret(tmp_path):
    assert resolve_attest_secret(tmp_path, {"exposed_asks": ["plain"]}, PLAIN) == ""
