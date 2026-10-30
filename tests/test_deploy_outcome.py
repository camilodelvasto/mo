# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The rail reports what the adapter says happened: Live or Staged, nothing else."""
import types
import pytest
from cli.commands.deploy import _report_outcome
from shapes.shared.adapters.outcome import Live, Staged

ADAPTER = types.SimpleNamespace(__name__="shared.adapters.hetzner")


def test_live_prints_url_and_done(capsys):
    _report_outcome(ADAPTER, Live("https://www.moui.io/"), mnemonic=None)
    assert capsys.readouterr().out == "  → https://www.moui.io/\n\n"


def test_staged_says_so_and_skips_done(capsys):
    _report_outcome(ADAPTER, Staged("https://www.moui.io/", "DNS points elsewhere"), mnemonic=None)
    out = capsys.readouterr().out
    assert out == "  STAGED (not live): DNS points elsewhere\n  → https://www.moui.io/\n"


def test_access_link_follows_the_url(capsys):
    _report_outcome(ADAPTER, Live("https://x.io/"), mnemonic="a b")
    out = capsys.readouterr().out
    assert "a b" in out and "https://x.io/#access=" in out and out.endswith("\n\n")


@pytest.mark.parametrize("bad", ["https://www.moui.io/", None, ("https://x", "r")])
def test_any_other_return_throws_naming_the_adapter(bad):
    with pytest.raises(SystemExit, match=r"shared\.adapters\.hetzner.*Live or Staged"):
        _report_outcome(ADAPTER, bad, mnemonic=None)
