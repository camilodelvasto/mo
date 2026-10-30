"""Tests for mo remote list/verify/setup commands."""
from pathlib import Path

import pytest
import yaml


def _write_remotes(tmp_path, remotes_dict):
    infra = tmp_path / "infrastructure"
    infra.mkdir(exist_ok=True)
    (infra / "remotes.yaml").write_text(
        yaml.dump({"remotes": remotes_dict}, default_flow_style=False)
    )


def _write_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text("secrets/\n")


# --- list ---


def test_list_shows_all_remotes(tmp_path, capsys):
    from cli.commands.remote import _list_remotes

    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "ssh-agent",
        },
        "hetzner/moui": {
            "adapter": "hetzner",
            "credential": "secrets/hetzner/moui.yaml",
        },
    })

    _list_remotes(tmp_path)
    out = capsys.readouterr().out
    assert "codeberg/moui-pages" in out
    assert "hetzner/moui" in out


def test_list_shows_adapter(tmp_path, capsys):
    from cli.commands.remote import _list_remotes

    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "ssh-agent",
        },
    })

    _list_remotes(tmp_path)
    out = capsys.readouterr().out
    assert "codeberg_pages" in out


def test_list_shows_ok_for_ssh_agent(tmp_path, capsys):
    from cli.commands.remote import _list_remotes

    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "ssh-agent",
        },
    })

    _list_remotes(tmp_path)
    out = capsys.readouterr().out
    assert "ok" in out


def test_list_shows_missing_for_absent_credential_file(tmp_path, capsys):
    from cli.commands.remote import _list_remotes

    _write_remotes(tmp_path, {
        "hetzner/moui": {
            "adapter": "hetzner",
            "credential": "secrets/hetzner/moui.yaml",
        },
    })

    _list_remotes(tmp_path)
    out = capsys.readouterr().out
    assert "missing" in out


# --- verify ---


def test_verify_ok(tmp_path, capsys):
    from cli.commands.remote import _verify_remote

    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "ssh-agent",
        },
    })

    _verify_remote(tmp_path, "codeberg/moui-pages")
    out = capsys.readouterr().out
    assert "credentials resolved" in out
    assert "codeberg_pages" in out


def test_verify_unknown_remote_exits(tmp_path, capsys):
    from cli.commands.remote import _verify_remote

    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "ssh-agent",
        },
    })

    with pytest.raises(SystemExit, match="1"):
        _verify_remote(tmp_path, "nonexistent/remote")

    out = capsys.readouterr().out
    assert "Unknown remote" in out


def test_verify_missing_credential_exits(tmp_path, capsys):
    from cli.commands.remote import _verify_remote

    _write_remotes(tmp_path, {
        "hetzner/moui": {
            "adapter": "hetzner",
            "credential": "secrets/hetzner/moui.yaml",
        },
    })

    with pytest.raises(SystemExit, match="1"):
        _verify_remote(tmp_path, "hetzner/moui")


def test_verify_masks_credential_values(tmp_path, capsys):
    from cli.commands.remote import _verify_remote

    secrets = tmp_path / "secrets" / "hetzner"
    secrets.mkdir(parents=True)
    (secrets / "moui.yaml").write_text(yaml.dump({"ssh_key": "~/.ssh/id_ed25519"}))

    _write_remotes(tmp_path, {
        "hetzner/moui": {
            "adapter": "hetzner",
            "credential": "secrets/hetzner/moui.yaml",
        },
    })

    _verify_remote(tmp_path, "hetzner/moui")
    out = capsys.readouterr().out
    assert "********" in out
    assert "~/.ssh/id_ed25519" not in out


# --- setup ---


def test_setup_refuses_without_gitignore(tmp_path, capsys):
    from cli.commands.remote import _setup_remote

    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "ssh-agent",
        },
    })

    with pytest.raises(SystemExit, match="1"):
        _setup_remote(tmp_path, "codeberg/moui-pages")

    out = capsys.readouterr().out
    assert "secrets/" in out
    assert ".gitignore" in out


def test_setup_refuses_gitignore_without_secrets(tmp_path, capsys):
    from cli.commands.remote import _setup_remote

    (tmp_path / ".gitignore").write_text("node_modules/\n")
    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "ssh-agent",
        },
    })

    with pytest.raises(SystemExit, match="1"):
        _setup_remote(tmp_path, "codeberg/moui-pages")


def test_setup_ssh_agent_needs_no_file(tmp_path, capsys):
    from cli.commands.remote import _setup_remote

    _write_gitignore(tmp_path)
    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "ssh-agent",
        },
    })

    _setup_remote(tmp_path, "codeberg/moui-pages")
    out = capsys.readouterr().out
    assert "ssh-agent" in out
    assert "no file needed" in out


def test_setup_unknown_remote_exits(tmp_path, capsys):
    from cli.commands.remote import _setup_remote

    _write_gitignore(tmp_path)
    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "ssh-agent",
        },
    })

    with pytest.raises(SystemExit, match="1"):
        _setup_remote(tmp_path, "nonexistent/remote")


def test_setup_skips_existing_credentials(tmp_path, capsys):
    from cli.commands.remote import _setup_remote

    _write_gitignore(tmp_path)
    secrets = tmp_path / "secrets" / "hetzner"
    secrets.mkdir(parents=True)
    (secrets / "moui.yaml").write_text("ssh_key: ~/.ssh/id\n")

    _write_remotes(tmp_path, {
        "hetzner/moui": {
            "adapter": "hetzner",
            "credential": "secrets/hetzner/moui.yaml",
        },
    })

    _setup_remote(tmp_path, "hetzner/moui")
    out = capsys.readouterr().out
    assert "already exist" in out


def test_setup_creates_credential_file(tmp_path, capsys, monkeypatch):
    from cli.commands.remote import _setup_remote

    _write_gitignore(tmp_path)
    _write_remotes(tmp_path, {
        "hetzner/moui": {
            "adapter": "hetzner",
            "credential": "secrets/hetzner/moui.yaml",
        },
    })

    prompts = []
    inputs = iter(["~/.ssh/id_ed25519"])
    monkeypatch.setattr("builtins.input", lambda p: (prompts.append(p), next(inputs))[1])

    _setup_remote(tmp_path, "hetzner/moui")

    cred_file = tmp_path / "secrets" / "hetzner" / "moui.yaml"
    assert cred_file.read_text() == "ssh_key: ~/.ssh/id_ed25519\n"
    assert len(prompts) == 1 and "passphrase" not in prompts[0].lower()


def test_setup_without_adapter_names_the_remote(tmp_path, capsys):
    from cli.commands.remote import _setup_remote

    _write_gitignore(tmp_path)
    _write_remotes(tmp_path, {
        "hetzner/bare": {"host": "h", "credential": "secrets/hetzner/bare.yaml"},
    })

    with pytest.raises(SystemExit, match="hetzner/bare.*adapter"):
        _setup_remote(tmp_path, "hetzner/bare")
    assert not (tmp_path / "secrets" / "hetzner" / "bare.yaml").exists()


def test_setup_ssh_agent_without_adapter_needs_no_file(tmp_path, capsys):
    """hetzner/hub shape: ssh-agent, no adapter key — returns before the adapter check."""
    from cli.commands.remote import _setup_remote

    _write_gitignore(tmp_path)
    _write_remotes(tmp_path, {
        "hetzner/box": {"host": "h", "user": "root", "path": "/opt/cs", "credential": "ssh-agent"},
    })

    _setup_remote(tmp_path, "hetzner/box")
    assert "no file needed" in capsys.readouterr().out


def test_setup_pages_adapter_prompts_token(tmp_path, capsys, monkeypatch):
    from cli.commands.remote import _setup_remote

    _write_gitignore(tmp_path)
    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "secrets/codeberg/moui-pages.yaml",
        },
    })

    monkeypatch.setattr("builtins.input", lambda _: "my-secret-token")

    _setup_remote(tmp_path, "codeberg/moui-pages")

    cred_file = tmp_path / "secrets" / "codeberg" / "moui-pages.yaml"
    assert cred_file.exists()
    content = cred_file.read_text()
    assert "token: my-secret-token" in content


# --- run dispatcher ---


def test_run_no_args_exits(tmp_path, capsys):
    from cli.commands.remote import run

    with pytest.raises(SystemExit, match="1"):
        run(tmp_path, [])

    out = capsys.readouterr().out
    assert "Usage" in out


def test_run_unknown_subcommand_exits(tmp_path, capsys):
    from cli.commands.remote import run

    with pytest.raises(SystemExit, match="1"):
        run(tmp_path, ["bogus"])

    out = capsys.readouterr().out
    assert "Unknown subcommand" in out


def test_run_list_dispatches(tmp_path, capsys):
    from cli.commands.remote import run

    _write_remotes(tmp_path, {
        "codeberg/moui-pages": {
            "adapter": "codeberg_pages",
            "credential": "ssh-agent",
        },
    })

    run(tmp_path, ["list"])
    out = capsys.readouterr().out
    assert "codeberg/moui-pages" in out


def test_run_verify_no_id_exits(tmp_path, capsys):
    from cli.commands.remote import run

    with pytest.raises(SystemExit, match="1"):
        run(tmp_path, ["verify"])

    out = capsys.readouterr().out
    assert "Usage" in out


def test_run_setup_no_id_exits(tmp_path, capsys):
    from cli.commands.remote import run

    with pytest.raises(SystemExit, match="1"):
        run(tmp_path, ["setup"])

    out = capsys.readouterr().out
    assert "Usage" in out
