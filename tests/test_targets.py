"""Tests for infrastructure/targets/ loading."""
from pathlib import Path

import pytest
import yaml


def _write_target(tmp_path, rel_path, target_dict):
    target_path = tmp_path / "infrastructure" / "targets" / rel_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(yaml.dump(target_dict, default_flow_style=False))


def _minimal_remote():
    return {
        "adapter": "codeberg_pages",
        "repo": "git@codeberg.org:moui/pages.git",
        "branch": "pages",
        "git_user": "bot",
        "git_email": "bot@x",
        "credential": "ssh-agent",
    }


def test_load_target_from_content_dir(tmp_path):
    from cli.infra.targets import load_target

    content_dir = tmp_path / "content" / "moui" / "website" / "en"
    content_dir.mkdir(parents=True)

    _write_target(tmp_path, "moui/website/en.yaml", {
        "content": "moui/website/en",
        "shape": "grove",
        "environments": {
            "prod": {
                "domain": "moui.io",
                "base_path": "/",
                "encrypted": False,
                "remote": "codeberg/moui-pages",
                "publish_path": "/",
            }
        }
    })

    target = load_target(content_dir, tmp_path)
    assert target["shape"] == "grove"
    assert "prod" in target["environments"]


def test_load_target_from_file_path(tmp_path):
    from cli.infra.targets import load_target

    content_file = tmp_path / "content" / "moui" / "decks" / "pitch-deck.yaml"
    content_file.parent.mkdir(parents=True)
    content_file.write_text("title: Pitch")

    _write_target(tmp_path, "moui/decks/pitch-deck.yaml", {
        "content": "moui/decks/pitch-deck.yaml",
        "shape": "deck",
        "environments": {
            "live": {
                "domain": "pitch.moui.io",
                "base_path": "/",
                "encrypted": False,
                "remote": "codeberg/moui-pages",
                "publish_path": "/pitch",
            }
        }
    })

    target = load_target(content_file, tmp_path)
    assert target["shape"] == "deck"


def test_load_target_raises_when_missing(tmp_path):
    from cli.infra.targets import load_target, TargetError

    content_dir = tmp_path / "content" / "moui" / "wiki"
    content_dir.mkdir(parents=True)

    with pytest.raises(TargetError, match="No target file"):
        load_target(content_dir, tmp_path)


def test_get_environment_raises_on_unknown(tmp_path):
    from cli.infra.targets import load_target, get_environment, TargetError

    content_dir = tmp_path / "content" / "moui" / "website" / "en"
    content_dir.mkdir(parents=True)

    _write_target(tmp_path, "moui/website/en.yaml", {
        "content": "moui/website/en",
        "shape": "grove",
        "environments": {
            "prod": {
                "domain": "moui.io",
                "base_path": "/",
                "encrypted": False,
                "remote": "codeberg/moui-pages",
                "publish_path": "/",
            }
        }
    })

    target = load_target(content_dir, tmp_path)
    with pytest.raises(TargetError, match=r"(?s)staging.*Available.*prod"):
        get_environment(target, "staging")


def test_derive_base_url():
    from cli.infra.targets import derive_base_url

    env = {"domain": "moui.io", "base_path": "/"}
    assert derive_base_url(env) == "https://moui.io/"

    env2 = {"domain": "moui.io", "base_path": "/grove"}
    assert derive_base_url(env2) == "https://moui.io/grove"


def test_validate_remote_refs(tmp_path):
    from cli.infra.targets import load_target, validate_remote_refs, TargetError

    content_dir = tmp_path / "content" / "moui" / "website" / "en"
    content_dir.mkdir(parents=True)

    _write_target(tmp_path, "moui/website/en.yaml", {
        "content": "moui/website/en",
        "shape": "grove",
        "environments": {
            "prod": {
                "domain": "moui.io",
                "base_path": "/",
                "encrypted": False,
                "remote": "codeberg/typo",
                "publish_path": "/",
            }
        }
    })

    target = load_target(content_dir, tmp_path)
    known_remotes = {"codeberg/moui-pages": _minimal_remote()}

    with pytest.raises(TargetError, match=r"(?s)codeberg/typo.*Known remotes:"):
        validate_remote_refs(target, known_remotes)


def test_declared_mounts_sees_every_remote_for_the_domain(tmp_path):
    from cli.infra.targets import declared_mounts
    t = tmp_path / "infrastructure" / "targets"
    (t / "a").mkdir(parents=True)
    (t / "a/en.yaml").write_text(
        "shape: grove\nenvironments:\n"
        "  prod: {remote: hetzner/web, domain: www.moui.io, publish_path: /}\n"
        "  staging: {remote: hetzner/web, domain: next.moui.co, publish_path: /}\n"
        "  gh: {remote: github/g, domain: www.moui.io, publish_path: /}\n")
    (t / "a/es.yaml").write_text(
        "shape: grove\nenvironments:\n"
        "  prod: {remote: hetzner/web, domain: www.moui.io, publish_path: /es}\n"
        "  cb: {remote: codeberg/c, domain: www.moui.io, publish_path: /es/}\n")
    en, es = "infrastructure/targets/a/en.yaml", "infrastructure/targets/a/es.yaml"
    assert declared_mounts(tmp_path, "www.moui.io") == {
        "/": [("github/g", en), ("hetzner/web", en)],
        "/es": [("hetzner/web", es)],
        "/es/": [("codeberg/c", es)]}                 # spelled as declared; the adapter canonicalises
    assert declared_mounts(tmp_path, "next.moui.co") == {"/": [("hetzner/web", en)]}


def _grove(tmp_path, rel, body):
    f = tmp_path / "infrastructure" / "targets" / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("shape: grove\nenvironments:\n" + body)


def test_declared_paths_by_remote_groups_by_remote(tmp_path):
    from cli.infra.targets import declared_paths_by_remote
    _grove(tmp_path, "a/en.yaml",
           "  prod: {remote: hetzner/web, domain: www.moui.io, publish_path: /}\n"
           "  gh: {remote: github/g, domain: www.moui.io, publish_path: /g}\n")
    _grove(tmp_path, "a/es.yaml",
           "  prod: {remote: hetzner/web, domain: www.moui.io, publish_path: /es}\n"
           "  nopath: {remote: github/g, domain: www.moui.io}\n")
    assert declared_paths_by_remote(tmp_path) == {"hetzner/web": {"/", "/es"},
                                                  "github/g": {"/g"}}


def test_declared_paths_by_remote_without_targets_dir_is_empty(tmp_path):
    from cli.infra.targets import declared_paths_by_remote
    assert declared_paths_by_remote(tmp_path) == {}


def test_declared_mounts_malformed_file_throws(tmp_path):
    from cli.infra.targets import TargetError, declared_mounts
    bad = tmp_path / "infrastructure" / "targets" / "bad.yaml"
    bad.parent.mkdir(parents=True)
    bad.write_text("shape: grove\n")
    with pytest.raises(TargetError, match=r"bad\.yaml[\s\S]*Deploy and reconcile need complete visibility"):
        declared_mounts(tmp_path, "www.moui.io")


def test_declared_mounts_matching_env_without_publish_path_throws(tmp_path):
    from cli.infra.targets import TargetError, declared_mounts
    _grove(tmp_path, "a/en.yaml", "  prod: {remote: hetzner/web, domain: www.moui.io}\n")
    with pytest.raises(TargetError, match=r"en\.yaml.*no publish_path"):
        declared_mounts(tmp_path, "www.moui.io")
