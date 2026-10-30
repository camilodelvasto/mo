# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import yaml


def _prod_env():
    return {
        "remote": "hetzner/elections-box",
        "domain": "api.elections.example",
        "corpus": "elections-co",
        "capabilities": "box",
        "exposed_asks": ["chat", "search"],
        "auth": {"scheme": "access-code"},
        "roles": {"standard": {"cap": 500}, "trial": {"cap": 50}},
        "default_role": "standard",
        "window": "month",
        "rate_limit": {"per_minute": 60, "block_after": 10, "block_for": "15m"},
    }


def test_render_dotenv_carries_scalars_only():
    from corpus_server.compile import render
    dotenv, gate = render(_prod_env(), grove_origins=["https://elections.example"], sites_dir="/data/sites",
                          aws_credentials_file="/run/secrets/aws",
                          host_root="/data")
    assert "DOMAIN=api.elections.example" in dotenv
    assert r"GROVE_ORIGIN_RE='https://elections\.example'" in dotenv
    assert "CORPUS_DIR=/data/corpus/elections-co" in dotenv
    assert "AWS_SHARED_CREDENTIALS_FILE=/run/secrets/aws" in dotenv
    assert "CAPABILITIES=/data/capabilities.yaml" in dotenv
    # no structured policy leaks into .env
    assert "exposed_asks" not in dotenv
    assert "roles" not in dotenv
    assert "500" not in dotenv


def test_render_gate_carries_structured_policy():
    from corpus_server.compile import render
    _, gate = render(_prod_env(), grove_origins=["https://elections.example"], sites_dir="/data/sites",
                     aws_credentials_file="/run/secrets/aws",
                     host_root="/data")
    assert gate["exposed_asks"] == ["chat", "search"]
    assert gate["auth"]["scheme"] == "access-code"
    # access list lives under the box-config DIR mount (not a fragile file mount)
    assert gate["auth"]["access_list"] == "/data/box-config/access.csv"
    assert gate["roles"]["standard"]["cap"] == 500
    assert gate["default_role"] == "standard"
    assert gate["window"] == "month"
    assert gate["rate_limit"]["per_minute"] == 60
    # the gate config the renderer emits must load clean
    from corpus_server.gate.config import load_gate_config
    import tempfile, pathlib
    p = pathlib.Path(tempfile.mkdtemp()) / "gate.yaml"
    p.write_text(yaml.dump(gate))
    load_gate_config(p)   # raises if the rendered shape is wrong


def test_render_rejects_unknown_auth_scheme():
    import pytest
    from corpus_server.compile import render
    bad_env = dict(_prod_env(), auth={"scheme": "acces-code"})  # typo
    with pytest.raises(ValueError, match="unknown auth scheme"):
        render(bad_env, grove_origins=["https://elections.example"], sites_dir="/data/sites",
               aws_credentials_file="/run/secrets/aws",
               host_root="/data")


def test_switching_env_changes_only_values():
    from corpus_server.compile import render
    prod_env, gate_p = render(_prod_env(), grove_origins=["https://elections.example"], sites_dir="/data/sites",
                              aws_credentials_file="/run/secrets/aws",
                              host_root="/data")
    staging = dict(_prod_env(), domain="api-staging.elections.example",
                   corpus="elections-co-staging", auth={"scheme": "none"})
    staging_env, gate_s = render(staging, grove_origins=["https://elections.example"], sites_dir="/data/sites",
                                 aws_credentials_file="/run/secrets/aws",
                                 host_root="/data")
    assert "api-staging.elections.example" in staging_env
    assert gate_s["auth"]["scheme"] == "none"
    assert gate_p["auth"]["scheme"] == "access-code"   # prod render unaffected


def test_render_env_uses_host_root_for_mount_sources():
    from corpus_server.compile import render
    dotenv, _ = render(_prod_env(), grove_origins=["https://e.example"], sites_dir="/data/sites",
                       aws_credentials_file="/run/secrets/aws",
                       host_root="/opt/corpus-server")
    assert "CORPUS_DIR=/opt/corpus-server/corpus/elections-co" in dotenv
    assert "CAPABILITIES=/opt/corpus-server/capabilities.yaml" in dotenv
    assert "BOX_CONFIG=/opt/corpus-server/box-config" in dotenv


def test_render_gate_keeps_container_paths_fixed_regardless_of_host_root():
    from corpus_server.compile import render
    _, gate = render(_prod_env(), grove_origins=["https://e.example"], sites_dir="/data/sites",
                     aws_credentials_file="/run/secrets/aws",
                     host_root="/opt/corpus-server")
    assert gate["ledger"] == "/data/ledger.jsonl"
    assert gate["auth"]["access_list"] == "/data/box-config/access.csv"


def test_render_requires_host_root():
    import pytest
    from corpus_server.compile import render
    with pytest.raises(TypeError):
        render(_prod_env(), grove_origins=["https://e.example"], sites_dir="/data/sites",
               aws_credentials_file="/run/secrets/aws")


def test_compiled_env_covers_every_compose_variable():
    import re
    from pathlib import Path
    from corpus_server.compile import render
    compose_path = Path("infrastructure/corpus-server/docker-compose.yml")
    if not compose_path.is_file():
        pytest.skip("docker-compose.yml not present (gitignored, present only on a working checkout)")
    compose = compose_path.read_text()
    referenced = set(re.findall(r"\$\{(\w+)(?::[-?][^}]*)?\}", compose))
    defaulted = set(re.findall(r"\$\{(\w+):-[^}]*\}", compose))
    dotenv, _ = render(_prod_env(), grove_origins=["https://e.example"], sites_dir="/data/sites",
                       aws_credentials_file="/run/secrets/aws",
                       host_root="/opt/corpus-server")
    present = {line.split("=", 1)[0] for line in dotenv.splitlines() if "=" in line}
    missing = referenced - defaulted - present
    assert not missing, f"compose vars not in .env and without default: {missing}"


def test_render_rejects_role_asks_outside_exposed():
    import pytest
    from corpus_server.compile import render
    bad = dict(_prod_env(), exposed_asks=["chat"],
               roles={"r": {"cap": 5, "asks": ["chat", "ghost"]}})  # ghost not exposed
    with pytest.raises(ValueError, match="ghost"):
        render(bad, grove_origins=["https://e.example"], sites_dir="/data/sites",
               aws_credentials_file="/run/secrets/aws", host_root="/opt/corpus-server")


def test_render_accepts_role_asks_subset_of_exposed():
    from corpus_server.compile import render
    ok = dict(_prod_env(), exposed_asks=["chat", "search"],
              roles={"r": {"cap": 5, "asks": ["chat"]}})
    render(ok, grove_origins=["https://e.example"], sites_dir="/data/sites",
           aws_credentials_file="/run/secrets/aws", host_root="/opt/corpus-server")  # no raise


def test_dotenv_carries_the_attest_secret_mount_source():
    # The box signs canonical attachments with it; compose mounts it at
    # /app/attest.secret, where serve's machine_root looks.
    from corpus_server.compile import render
    dotenv, _ = render(_prod_env(), grove_origins=["https://e.example"], sites_dir="/data/sites",
                       aws_credentials_file="/run/secrets/aws", host_root="/opt/cs")
    assert "ATTEST_SECRET=/opt/cs/secrets/attest.secret" in dotenv


def test_render_grove_origin_re_is_an_anchorable_alternation():
    from corpus_server.compile import render
    dotenv, _ = render(_prod_env(),
                       grove_origins=["https://www.moui.io", "https://next.moui.co"],
                       aws_credentials_file="/run/secrets/aws", host_root="/data",
                       sites_dir="/data/sites")
    assert r"GROVE_ORIGIN_RE='https://www\.moui\.io|https://next\.moui\.co'" in dotenv
    assert "SITES_DIR=/data/sites" in dotenv
    assert "GROVE_ORIGIN=" not in dotenv
    assert "GROVE_ORIGINS" not in dotenv   # the API host's CSP carries no origin list


def test_render_grove_origins_must_be_canonical_list():
    import pytest
    from corpus_server.compile import render
    kw = dict(aws_credentials_file="/a", host_root="/data", sites_dir="/data/sites")
    with pytest.raises(ValueError, match="non-empty list"):
        render(_prod_env(), grove_origins="https://www.moui.io", **kw)
    with pytest.raises(ValueError, match="non-empty list"):
        render(_prod_env(), grove_origins=[], **kw)
    with pytest.raises(ValueError, match="canonical"):
        render(_prod_env(), grove_origins=["https://www.moui.io/"], **kw)


def test_render_grove_origins_entries_are_plain_origins():
    import pytest
    from corpus_server.compile import render
    kw = dict(aws_credentials_file="/a", host_root="/data", sites_dir="/data/sites")
    for bad in (["https://www.moui.io'"], ["https://www.moui.io|https://evil.co"],
                ["ftp://www.moui.io"], ["https://www.moui.io:8443/x"],
                ["https://WWW.moui.io"]):
        with pytest.raises(ValueError, match="grove_origins entry"):
            render(_prod_env(), grove_origins=bad, **kw)
    with pytest.raises(ValueError, match="grove_origins entry 443 is not a str"):
        render(_prod_env(), grove_origins=[443], **kw)
    dotenv, _ = render(_prod_env(), grove_origins=["http://localhost:4200"], **kw)
    assert "GROVE_ORIGIN_RE='http://localhost:4200'" in dotenv
