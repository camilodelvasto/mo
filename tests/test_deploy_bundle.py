# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path
from cli.deploy.bundle import stage_bundle, INCLUDE


def _fake_repo(root: Path):
    (root / "pyproject.toml").write_text("[project]\n")
    (root / "moui.json").write_text("{}")
    for d in ("cli", "shapes", "bin", "corpus_server",
              "infrastructure/corpus-server"):
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / "keep.txt").write_text("x")
    (root / "secrets").mkdir(); (root / "secrets" / "aws").write_text("KEY")
    (root / "content").mkdir(); (root / "content" / "corpus").write_text("DATA")
    (root / "capabilities.yaml").write_text("capabilities: {}")


def test_bundle_contains_the_logic_include_list(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); _fake_repo(repo)
    stage = stage_bundle(repo, "DOMAIN=x\n", "upstream: y\n", tmp_path / "stage")
    for item in INCLUDE:
        assert (stage / item).exists(), f"missing logic path: {item}"
    assert (stage / "box-config" / ".env").read_text() == "DOMAIN=x\n"
    assert (stage / "box-config" / "gate.yaml").read_text() == "upstream: y\n"


def test_bundle_excludes_every_datum_and_secret(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); _fake_repo(repo)
    stage = stage_bundle(repo, "e\n", "g\n", tmp_path / "stage")
    assert not (stage / "secrets").exists()
    assert not (stage / "content").exists()
    staged = {p.name for p in stage.rglob("*")}
    assert "aws" not in staged
    # capabilities.yaml is placed via box.put_file (inode-preserving), NOT shipped
    # in the bundle — so no capabilities.yaml rides the tar at all.
    assert "capabilities.yaml" not in staged


def test_bundle_is_reproducible_from_the_tree(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); _fake_repo(repo)
    a = stage_bundle(repo, "e\n", "g\n", tmp_path / "a")
    b = stage_bundle(repo, "e\n", "g\n", tmp_path / "b")
    names_a = sorted(str(p.relative_to(a)) for p in a.rglob("*"))
    names_b = sorted(str(p.relative_to(b)) for p in b.rglob("*"))
    assert names_a == names_b


def test_bundle_ships_no_capabilities_yaml_anywhere(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); _fake_repo(repo)
    # plant a per-instance capabilities.yaml under infrastructure/corpus-server/acme/
    instance_dir = repo / "infrastructure" / "corpus-server" / "acme"
    instance_dir.mkdir(parents=True, exist_ok=True)
    (instance_dir / "capabilities.yaml").write_text("capabilities:\n  stale: {}\n")
    stage = stage_bundle(repo, "e\n", "g\n", tmp_path / "stage")
    # the per-instance copy swept in by the infrastructure sweep is pruned, and
    # nothing writes a box-root copy — capabilities rides put_file, never the bundle.
    assert list(stage.rglob("capabilities.yaml")) == []


def test_bundle_ships_the_stack_but_never_dev_data(tmp_path):
    # dev/ holds a local access.csv, attest.secret, ledgers and logs — data and
    # secrets, which the include-list exists to keep off the box.
    repo = tmp_path / "repo"; repo.mkdir(); _fake_repo(repo)
    stack = repo / "infrastructure" / "corpus-server"
    (stack / "caddy").mkdir()
    (stack / "caddy" / "Caddyfile").write_text("import /srv/sites/*.caddy\n")
    (stack / "docker-compose.yml").write_text("services: {}\n")
    (stack / "dev").mkdir()
    for name in ("access.csv", "attest.secret", "ledger-2026-09.jsonl", "caddy-access.log"):
        (stack / "dev" / name).write_text("SECRET")
    stage = stage_bundle(repo, "e\n", "g\n", tmp_path / "stage")
    staged = stage / "infrastructure" / "corpus-server"
    assert (staged / "caddy" / "Caddyfile").is_file()
    assert (staged / "docker-compose.yml").is_file()
    assert not (staged / "dev").exists()
