# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from cli.deploy import caps
from cli.deploy.caps import required_caps

# Grounded in acme's real ask.yaml: find retrieve-only; answer synthesize;
# converse/explorar BOTH decompose + synthesize.
_ASK = {"asks": [
    {"id": "find", "retrieve": {"mode": "hybrid", "k": 12}},
    {"id": "answer", "synthesize": {"uses": "api.claude-json"}},
    {"id": "converse", "decompose": {"uses": "api.claude"},
     "synthesize": {"uses": "api.claude-json"}},
    {"id": "explorar", "decompose": {"uses": "api.claude"},
     "synthesize": {"uses": "api.claude-json"}},
]}


def test_unions_synthesize_and_decompose():
    assert required_caps(_ASK, ["find", "answer", "converse", "explorar"]) == \
        {"api.claude", "api.claude-json"}


def test_skips_retrieve_only_ask():
    assert required_caps(_ASK, ["find"]) == set()


def test_misses_nothing_when_cap_only_in_decompose():
    # the regression the field-path grounding caught: decompose-only drops this
    assert "api.claude" in required_caps(_ASK, ["converse"])


def test_undefined_exposed_ask_fails_loud():
    with pytest.raises(ValueError, match="ghost"):
        required_caps(_ASK, ["ghost"])


def test_bound_caps_reads_capability_keys():
    from cli.deploy.caps import bound_caps
    caps = {"capabilities": {"api.claude": {}, "api.claude-json": {}}}
    assert bound_caps(caps) == {"api.claude", "api.claude-json"}


def test_shims_present_passes_when_bin_has_the_shim(tmp_path):
    from cli.deploy.caps import shims_present
    (tmp_path / "bin").mkdir(); (tmp_path / "bin" / "claude-bedrock").write_text("x")
    caps = {"capabilities": {"api.claude":
            {"run": ["/app/bin/claude-bedrock", "--model", "m"]}}}
    shims_present(caps, tmp_path)                       # no raise


def test_shims_present_fails_when_shim_missing_from_bin(tmp_path):
    import pytest
    from cli.deploy.caps import shims_present
    (tmp_path / "bin").mkdir()
    caps = {"capabilities": {"api.claude-json":
            {"run": ["/app/bin/claude-bedrock-json", "--model", "m"]}}}
    with pytest.raises(ValueError, match="claude-bedrock-json"):
        shims_present(caps, tmp_path)


# --- attachments: the declaration pulls in its own capability + secret -------------
# An ask that declares `attachments:` needs media.image (the /verify canonicalizer),
# which no `uses:` key names — the declaration is the requirement. It also needs the
# box to hold an attest secret, or /verify 500s at the first upload.

ATT_ASKS = {"asks": [
    {"id": "mira", "attachments": {"accept": ["image"]},
     "synthesize": {"uses": "api.claude-vision", "prompt": "p"}},
    {"id": "plain", "synthesize": {"uses": "api.claude-json", "prompt": "p"}}]}


def test_an_attachments_ask_requires_media_image():
    assert caps.required_caps(ATT_ASKS, ["mira"]) == {"api.claude-vision", "media.image"}


def test_a_plain_ask_requires_no_media_capability():
    assert caps.required_caps(ATT_ASKS, ["plain"]) == {"api.claude-json"}


def test_attest_required_only_when_an_exposed_ask_declares_attachments():
    assert caps.attest_required(ATT_ASKS, ["mira"]) is True
    assert caps.attest_required(ATT_ASKS, ["plain"]) is False
    assert caps.attest_required(ATT_ASKS, ["plain", "mira"]) is True


def test_shims_present_checks_stream_bindings_too(tmp_path):
    # A stream-only binding (the vision capability has no run:) pointed at /app/bin
    # must still have its shim in the repo, or serve dies at the first ask.
    (tmp_path / "bin").mkdir()
    table = {"capabilities": {"api.claude-vision": {
        "stream": ["/app/bin/claude-bedrock-vision-stream", "--model", "m"], "reads": "envelope"}}}
    with pytest.raises(ValueError, match="claude-bedrock-vision-stream"):
        caps.shims_present(table, tmp_path)
    (tmp_path / "bin" / "claude-bedrock-vision-stream").write_text("#!/bin/sh\n")
    caps.shims_present(table, tmp_path)
