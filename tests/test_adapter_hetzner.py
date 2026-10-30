# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import pytest
import os
from shapes.shared.adapters import hetzner
from shapes.shared.adapters.hetzner import (
    HetznerError, mount_slug, canonical_path, release_id, site_config, _validate_config,
    RELEASE_MARKER)


def test_mount_slug():
    assert mount_slug("/") == "_root"
    assert mount_slug("/hub") == "hub"
    assert mount_slug("/a/b-c/") == "a--b-c"
    for bad in ("hub", "/A", "/a--b", "/a/../b", "/_x", "/a b"):
        with pytest.raises(HetznerError):
            mount_slug(bad)


def test_release_id_is_content_hash_ignoring_marker(tmp_path):
    (tmp_path / "index.html").write_text("a")
    (tmp_path / "sub").mkdir(); (tmp_path / "sub/x.js").write_text("b")
    rid = release_id(tmp_path)
    assert len(rid) == 16
    (tmp_path / RELEASE_MARKER).write_text(rid)
    assert release_id(tmp_path) == rid          # the marker never changes its own id
    (tmp_path / "sub/x.js").write_text("c")
    assert release_id(tmp_path) != rid


def test_validate_config_requires_fields_and_plain_names():
    ok = {"host": "ask.moui.co", "user": "root", "path": "/opt/cs", "domain": "www.moui.io"}
    _validate_config(ok)
    with pytest.raises(HetznerError, match="domain"):
        _validate_config({**ok, "domain": ""})
    with pytest.raises(HetznerError, match="localhost:4200"):
        _validate_config({**ok, "domain": "localhost:4200"})
    with pytest.raises(HetznerError, match="Moui.io"):
        _validate_config({**ok, "aliases": ["Moui.io"]})


def _m(path, spa=False, aliases=()):
    return {"publish_path": path, "spa": spa, "aliases": list(aliases)}


def test_site_config_nested_mounts_longest_first_root_last():
    cfg = site_config("www.moui.io", [_m("/", aliases=["moui.io"]), _m("/es"), _m("/hub", spa=True)])
    assert cfg == (
        "www.moui.io {\n"
        "\tencode gzip\n"
        "\theader -Server\n"
        "\theader Strict-Transport-Security \"max-age=31536000\"\n"
        "\tredir /hub /hub/ 308\n"
        "\thandle_path /hub/* {\n"
        "\t\troot * /srv/sites/www.moui.io/mounts/hub\n"
        "\t\ttry_files {path} /index.html\n"
        "\t\tfile_server\n"
        "\t}\n"
        "\tredir /es /es/ 308\n"
        "\thandle_path /es/* {\n"
        "\t\troot * /srv/sites/www.moui.io/mounts/es\n"
        "\t\tfile_server\n"
        "\t}\n"
        "\thandle {\n"
        "\t\troot * /srv/sites/www.moui.io/mounts/_root\n"
        "\t\tfile_server\n"
        "\t}\n"
        "\thandle_errors 404 {\n"
        "\t\thandle_path /hub/* {\n"
        "\t\t\troot * /srv/sites/www.moui.io/mounts/hub\n"
        "\t\t\trewrite * /404.html\n"
        "\t\t\tfile_server\n"
        "\t\t}\n"
        "\t\thandle_path /es/* {\n"
        "\t\t\troot * /srv/sites/www.moui.io/mounts/es\n"
        "\t\t\trewrite * /404.html\n"
        "\t\t\tfile_server\n"
        "\t\t}\n"
        "\t\thandle {\n"
        "\t\t\troot * /srv/sites/www.moui.io/mounts/_root\n"
        "\t\t\trewrite * /404.html\n"
        "\t\t\tfile_server\n"
        "\t\t}\n"
        "\t}\n"
        "}\n"
        "moui.io {\n"
        "\theader Strict-Transport-Security \"max-age=31536000\"\n"
        "\tredir https://www.moui.io{uri} 301\n"
        "}\n")


def test_site_config_hsts_on_every_block_without_subdomains():
    cfg = site_config("www.moui.io", [_m("/", aliases=["moui.io", "moui.co"])])
    blocks = [b for b in cfg.split("\n}\n") if b.strip()]
    assert len(blocks) == 3
    for b in blocks:
        assert '\theader Strict-Transport-Security "max-age=31536000"\n' in b + "\n"
    assert "includeSubDomains" not in cfg          # other subdomains are not ours to pin


def test_site_config_without_root_mount_404s_the_rest():
    cfg = site_config("next.moui.co", [_m("/hub")])
    assert "\thandle {\n\t\terror 404\n\t}\n" in cfg


def test_site_config_deep_links_serve_the_mounts_404_shell():
    """The grove build writes 404.html as the app shell: an unknown path under a
    mount answers 404 with that mount's shell, so the SPA boots and routes."""
    cfg = site_config("www.moui.io", [_m("/"), _m("/es"), _m("/es/blog")])
    errors = cfg[cfg.index("\thandle_errors 404 {\n"):]
    order = [errors.index(f"handle_path {p}/* {{") for p in ("/es/blog", "/es")]
    assert order == sorted(order)                                  # longest first
    assert errors.index("handle_path /es/* {") < errors.index("\t\thandle {\n")   # root last
    for slug in ("es--blog", "es", "_root"):
        assert (f"root * /srv/sites/www.moui.io/mounts/{slug}\n"
                f"\t\t\trewrite * /404.html\n\t\t\tfile_server\n") in errors


def test_site_config_without_root_mount_has_no_root_404_rewrite():
    cfg = site_config("next.moui.co", [_m("/hub")])
    errors = cfg[cfg.index("\thandle_errors 404 {\n"):]
    assert "mounts/_root" not in errors and "\t\thandle {" not in errors
    assert errors.count("rewrite * /404.html") == 1                # the mount's own branch only


def test_site_config_refuses_empty():
    with pytest.raises(HetznerError, match="no mounts"):
        site_config("www.moui.io", [])


def test_canonical_path():
    assert canonical_path("/") == "/"
    assert canonical_path("/hub/") == "/hub"
    assert canonical_path("/a/b-c") == "/a/b-c"
    with pytest.raises(HetznerError):
        canonical_path("a")


def test_validate_config_aliases_list_and_not_domain():
    ok = {"host": "ask.moui.co", "user": "root", "path": "/opt/cs", "domain": "www.moui.io"}
    with pytest.raises(HetznerError, match="list"):
        _validate_config({**ok, "aliases": "moui.io"})
    with pytest.raises(HetznerError, match="www.moui.io"):
        _validate_config({**ok, "aliases": ["www.moui.io"]})


def test_release_id_counts_nested_marker_and_hashes_symlinks_by_target(tmp_path):
    (tmp_path / "index.html").write_text("a")
    (tmp_path / "sub").mkdir()
    rid = release_id(tmp_path)
    (tmp_path / "sub" / RELEASE_MARKER).write_text("x")
    assert release_id(tmp_path) != rid                 # only the top-level marker is excluded
    os.symlink("index.html", tmp_path / "link")
    with_link = release_id(tmp_path)
    (tmp_path / "link").unlink(); os.symlink("sub", tmp_path / "link")
    assert release_id(tmp_path) != with_link           # the target is hashed, not followed


def test_site_config_aliases_from_root_manifest_only():
    cfg = site_config("www.moui.io", [_m("/"), _m("/es", aliases=["stray.io"])])
    assert "stray.io" not in cfg
    cfg = site_config("www.moui.io", [_m("/", aliases=["moui.io"]), _m("/es")])
    assert "moui.io {\n\theader Strict-Transport-Security \"max-age=31536000\"\n\tredir https://www.moui.io{uri} 301\n}\n" in cfg


class _Run:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_verify_missing_curl_throws(monkeypatch):
    def run(*a, **k):
        raise FileNotFoundError("curl")
    monkeypatch.setattr(hetzner.subprocess, "run", run)
    with pytest.raises(HetznerError, match="curl"):
        hetzner._verify("www.moui.io", "/", "1.2.3.4", "r")


def test_verify_truncates_and_never_sleeps_after_last_attempt(monkeypatch):
    monkeypatch.setattr(hetzner, "VERIFY_TIMEOUT_S", 0)
    monkeypatch.setattr(hetzner.subprocess, "run", lambda *a, **k: _Run(7, stderr="e" * 500))
    def sleep(_):
        raise AssertionError("slept after the final attempt")
    monkeypatch.setattr(hetzner.time, "sleep", sleep)
    with pytest.raises(HetznerError) as exc:
        hetzner._verify("www.moui.io", "/", "1.2.3.4", "r")
    assert "e" * 120 in str(exc.value) and "e" * 121 not in str(exc.value)


def test_manifest_fields_leave_the_release_to_the_symlink():
    assert hetzner.MANIFEST_FIELDS == ("publish_path", "spa", "aliases")
