import pytest
from pathlib import Path
from unittest.mock import patch

from cli.sync.config import load_sync_declaration
from cli.sync.errors import (
    ConfigValidationError,
    InvalidRecipientError,
    RemoteNotFoundError,
)


def _setup_workspace(tmp_path):
    """Create a minimal workspace structure with infrastructure/remotes.yaml."""
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    syncs = infra / "syncs"
    syncs.mkdir()
    remotes = infra / "remotes.yaml"
    remotes.write_text("""\
remotes:
  codeberg/moui-sync:
    adapter: git_sync
    repo: git@codeberg.org:user/moui.git
    branch: main
    git_user: Test User
    git_email: test@example.com
    credential: ssh-agent
    commit_message: "moui-sync: {timestamp}"
  github/infra-sync:
    adapter: git_sync
    repo: git@github.com:user/infra.git
    branch: main
    git_user: Test User
    git_email: test@example.com
    credential: ssh-agent
    commit_message: "moui-sync: {timestamp}"
""")
    content = tmp_path / "content" / "moui"
    content.mkdir(parents=True)
    return tmp_path


def test_init_creates_declaration(tmp_path):
    """mo sync init <folder> --remote <id> creates infrastructure/syncs/<mirror>.yaml."""
    ws = _setup_workspace(tmp_path)
    folder = ws / "content" / "moui"

    from cli.sync.cli.init_cmd import run_init

    with patch("cli.sync.cli.init_cmd._verify_ssh_access"), \
         patch("cli.sync.git_sync.git_pull"):
        run_init(
            infrastructure_path=ws / "infrastructure",
            folder_path=folder,
            remote_id="codeberg/moui-sync",
            encryption="none",
            recipients=[],
        )

    decl_path = ws / "infrastructure" / "syncs" / "content" / "moui.yaml"
    assert decl_path.exists()
    decl = load_sync_declaration(decl_path)
    assert decl.remote == "codeberg/moui-sync"
    assert decl.encryption.type == "none"


def test_init_already_configured(tmp_path):
    """mo sync init raises if declaration already exists."""
    ws = _setup_workspace(tmp_path)
    folder = ws / "content" / "moui"
    decl_path = ws / "infrastructure" / "syncs" / "content" / "moui.yaml"
    decl_path.parent.mkdir(parents=True)
    decl_path.write_text("version: 1\ntarget: ../../../content/moui\nremote: x\nencryption:\n  type: none\n")

    from cli.sync.cli.init_cmd import run_init

    with pytest.raises(ConfigValidationError, match="already configured"):
        run_init(
            infrastructure_path=ws / "infrastructure",
            folder_path=folder,
            remote_id="codeberg/moui-sync",
            encryption="none",
            recipients=[],
        )


def test_init_folder_outside_tree(tmp_path):
    """mo sync init raises if folder is outside infrastructure parent tree."""
    ws = _setup_workspace(tmp_path)
    import tempfile
    with tempfile.TemporaryDirectory() as outside:
        from cli.sync.cli.init_cmd import run_init
        with pytest.raises(ConfigValidationError, match="same directory tree"):
            run_init(
                infrastructure_path=ws / "infrastructure",
                folder_path=Path(outside),
                remote_id="codeberg/moui-sync",
                encryption="none",
                recipients=[],
            )


def test_init_unknown_remote(tmp_path):
    """mo sync init raises if remote is not in remotes.yaml."""
    ws = _setup_workspace(tmp_path)
    folder = ws / "content" / "moui"

    from cli.sync.cli.init_cmd import run_init

    with pytest.raises(RemoteNotFoundError, match="nonexistent/remote"):
        run_init(
            infrastructure_path=ws / "infrastructure",
            folder_path=folder,
            remote_id="nonexistent/remote",
            encryption="none",
            recipients=[],
        )


def test_init_git_inits_folder(tmp_path):
    """mo sync init runs git init in the target folder."""
    ws = _setup_workspace(tmp_path)
    folder = ws / "content" / "moui"

    from cli.sync.cli.init_cmd import run_init

    with patch("cli.sync.cli.init_cmd._verify_ssh_access"), \
         patch("cli.sync.git_sync.git_pull"):
        run_init(
            infrastructure_path=ws / "infrastructure",
            folder_path=folder,
            remote_id="codeberg/moui-sync",
            encryption="none",
            recipients=[],
        )

    assert (folder / ".git").exists()


def test_init_computes_correct_target_path(tmp_path):
    """The target field resolves back to the original folder."""
    ws = _setup_workspace(tmp_path)
    folder = ws / "content" / "moui"

    from cli.sync.cli.init_cmd import run_init

    with patch("cli.sync.cli.init_cmd._verify_ssh_access"), \
         patch("cli.sync.git_sync.git_pull"):
        run_init(
            infrastructure_path=ws / "infrastructure",
            folder_path=folder,
            remote_id="codeberg/moui-sync",
            encryption="none",
            recipients=[],
        )

    decl_path = ws / "infrastructure" / "syncs" / "content" / "moui.yaml"
    decl = load_sync_declaration(decl_path)
    resolved = (decl_path.parent / decl.target).resolve()
    assert resolved == folder.resolve()


def test_init_rejects_invalid_ssh_pubkey():
    """age-ssh recipients must be valid SSH public keys."""
    from cli.sync.cli.init_cmd import _validate_ssh_pubkey

    _validate_ssh_pubkey("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyHere laptop")

    with pytest.raises(InvalidRecipientError):
        _validate_ssh_pubkey("not-a-key")

    with pytest.raises(InvalidRecipientError):
        _validate_ssh_pubkey("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAB laptop")


def test_init_reads_pub_file_as_recipient(tmp_path):
    """Pasting a .pub file path reads the key from the file."""
    pubfile = tmp_path / "mykey.pub"
    pubfile.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyHere laptop\n")

    from cli.sync.cli.init_cmd import _resolve_recipient

    result = _resolve_recipient(str(pubfile))
    assert result == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyHere laptop"


def test_verify_agent_keys_warns_on_mismatch(capsys):
    """If SSH agent has no matching key, warn but don't fail."""
    from cli.sync.cli.init_cmd import _check_agent_has_matching_key

    with patch("cli.sync.cli.init_cmd._get_agent_pubkeys", return_value=[
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAgentKeyHere agent"
    ]):
        _check_agent_has_matching_key([
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDifferentKeyHere laptop"
        ])
    output = capsys.readouterr().out
    assert "WARNING" in output
    assert "no matching key" in output.lower()


def test_verify_agent_keys_silent_on_match(capsys):
    """If SSH agent has a matching key, no warning."""
    from cli.sync.cli.init_cmd import _check_agent_has_matching_key

    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMatchingKey laptop"
    with patch("cli.sync.cli.init_cmd._get_agent_pubkeys", return_value=[key]):
        _check_agent_has_matching_key([key])
    output = capsys.readouterr().out
    assert "WARNING" not in output


def test_init_daemon_rescan_no_coroutine_warning(tmp_path):
    """init should not produce coroutine-not-awaited warnings."""
    import warnings
    ws = _setup_workspace(tmp_path)
    folder = ws / "content" / "moui"

    from cli.sync.cli.init_cmd import run_init

    with patch("cli.sync.cli.init_cmd._verify_ssh_access"), \
         patch("cli.sync.git_sync.git_pull"):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            run_init(
                infrastructure_path=ws / "infrastructure",
                folder_path=folder,
                remote_id="codeberg/moui-sync",
                encryption="none",
                recipients=[],
            )
        coroutine_warnings = [x for x in w if "coroutine" in str(x.message).lower()]
        assert coroutine_warnings == [], f"Got coroutine warnings: {coroutine_warnings}"


def test_parse_args():
    """CLI arg parsing extracts all flags correctly."""
    from cli.sync.cli.init_cmd import _parse_args

    parsed = _parse_args([
        "content", "--remote", "github/sync", "--encryption", "age-ssh",
        "--recipients", "ssh-ed25519 KEY1 laptop", "ssh-ed25519 KEY2 work",
    ])
    assert parsed["folder"] == "content"
    assert parsed["remote"] == "github/sync"
    assert parsed["encryption"] == "age-ssh"
    assert parsed["recipients"] == ["ssh-ed25519 KEY1 laptop", "ssh-ed25519 KEY2 work"]


def test_parse_args_minimal():
    """Minimal args: just folder and remote."""
    from cli.sync.cli.init_cmd import _parse_args

    parsed = _parse_args(["content", "--remote", "github/sync"])
    assert parsed["folder"] == "content"
    assert parsed["remote"] == "github/sync"
    assert parsed["encryption"] == "none"
    assert parsed["recipients"] == []
