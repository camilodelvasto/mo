import subprocess
import textwrap
from pathlib import Path

import pytest


@pytest.fixture()
def workspace_root(tmp_path: Path) -> Path:
    (tmp_path / ".moui").mkdir()
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / ".moui").mkdir()
    (tmp_path / "infrastructure").mkdir()
    return tmp_path


@pytest.fixture()
def workspace_yaml_text() -> str:
    return textwrap.dedent("""\
        version: 1
        workspace:
          id: 01JTEST0000WORKSPACE00001
          display_name: test-workspace
          infrastructure:
            folder: infrastructure
            bootstrap_repo: git@github.com:test/infra.git
            bootstrap_branch: main
        folders:
          content:
            remote: git@github.com:test/content.git
            encryption:
              type: none
            sync:
              debounce_seconds: 30
              max_debounce_seconds: 300
          infrastructure:
            remote: git@github.com:test/infra.git
            encryption:
              type: age-ssh
              recipients:
                - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey1
                - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey2
        sync:
          debounce_seconds: 10
          max_debounce_seconds: 60
          commit_message: "auto-sync: {timestamp}"
    """)


@pytest.fixture()
def device_yaml_text() -> str:
    return textwrap.dedent("""\
        version: 1
        device:
          id: 01JTEST0000DEVICE0000001
          display_name: test-device
          workspace_id: 01JTEST0000WORKSPACE00001
          workspace_root: /tmp/ws
          bootstrap_folder: infrastructure
    """)


@pytest.fixture()
def written_workspace(
    workspace_root: Path,
    workspace_yaml_text: str,
    device_yaml_text: str,
) -> Path:
    (workspace_root / ".moui" / "workspace.yaml").write_text(workspace_yaml_text)
    (workspace_root / ".moui" / "device.yaml").write_text(device_yaml_text)
    return workspace_root


@pytest.fixture()
def bare_repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("bare") / "test.git"
    subprocess.run(["git", "init", "--bare", str(repo)], check=True, capture_output=True)
    return repo


@pytest.fixture()
def remotes_yaml(workspace_root: Path) -> Path:
    path = workspace_root / ".moui" / "remotes.yaml"
    path.write_text(textwrap.dedent("""\
        remotes:
          content:
            adapter: git_sync
            url: git@github.com:test/content.git
          infrastructure:
            adapter: git_sync
            url: git@github.com:test/infra.git
    """))
    return path
