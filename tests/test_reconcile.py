# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""mo reconcile works on git-pages remotes only; any other adapter refuses by name."""
import pytest
from cli.commands import reconcile


def _root(tmp_path, adapter):
    infra = tmp_path / "infrastructure"
    (infra / "targets").mkdir(parents=True)
    (infra / "remotes.yaml").write_text(
        "remotes:\n"
        "  hetzner/web:\n"
        f"    adapter: {adapter}\n"
        "    host: ask.moui.co\n    user: root\n    path: /opt/cs\n"
        "    credential: ssh-agent\n    service_worker: true\n")
    return tmp_path


@pytest.mark.parametrize("adapter", ["hetzner", "s3"])
def test_non_git_pages_remote_refuses_by_name(tmp_path, adapter):
    with pytest.raises(SystemExit, match=rf"hetzner/web.*{adapter}.*codeberg_pages, github_pages"):
        reconcile.run(_root(tmp_path, adapter), ["hetzner/web"])


def test_stack_remote_without_adapter_refuses_by_name(tmp_path):
    # A stack remote (converged, not copied to) declares no adapter at all.
    infra = tmp_path / "infrastructure"
    (infra / "targets").mkdir(parents=True)
    (infra / "remotes.yaml").write_text(
        "remotes:\n  hetzner/box:\n    host: ask.moui.co\n    user: root\n"
        "    path: /opt/cs\n    credential: ssh-agent\n")
    with pytest.raises(SystemExit, match=r"hetzner/box declares no adapter.*stack remote"):
        reconcile.run(tmp_path, ["hetzner/box"])
