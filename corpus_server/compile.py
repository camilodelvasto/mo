# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Turn one target environment into the two flat artifacts the committed stack
consumes: .env (scalars Caddy + compose substitute from) and gate.yaml (the
structured policy the gate reads). The compile owns the corpus-server config
shape across both artifacts; the adapter never learns it."""
import re
import sys
from pathlib import Path

import yaml

# The container root where the gate's compose volumes mount (ledger:/data,
# ${BOX_CONFIG}:/data/box-config). A contract with the committed compose file,
# NOT a per-deploy value — gate.yaml paths are read inside the container.
_CONTAINER_ROOT = "/data"


_ORIGIN = re.compile(r"https?://[a-z0-9.-]+(:\d+)?")


def _origin_alternation(origins) -> str:
    """An alternation for Caddy's anchored header_regexp (CORS echo). Each entry
    must be a plain scheme://host[:port] — then only '.' is a regex metacharacter
    and nothing can break the .env quoting. Lazy import: the gate image carries
    corpus_server only."""
    from cli.infra.origin import origin_of
    if not isinstance(origins, list) or not origins:
        raise ValueError("grove_origins must be a non-empty list of origins")
    for o in origins:
        if not isinstance(o, str):
            raise ValueError(f"grove_origins entry {o!r} is not a str")
        if not _ORIGIN.fullmatch(o) or origin_of(o) != o:
            raise ValueError(f"grove_origins entry {o!r} is not a canonical origin "
                             f"(lowercase scheme://host[:port], http or https, "
                             f"no default port, no path)")
    return "|".join(o.replace(".", r"\.") for o in origins)


def render(env: dict, *, grove_origins: list, aws_credentials_file: str,
           host_root: str, sites_dir: str) -> tuple[str, dict]:
    corpus = env["corpus"]
    alternation = _origin_alternation(grove_origins)
    # .env vars are docker mount SOURCES → box-HOST paths under host_root.
    # Single quotes: compose reads them literally (the regex keeps its backslashes).
    dotenv = "\n".join([
        f"DOMAIN={env['domain']}",
        f"GROVE_ORIGIN_RE='{alternation}'",
        f"SITES_DIR={sites_dir}",
        f"CORPUS_DIR={host_root}/corpus/{corpus}",
        f"CAPABILITIES={host_root}/capabilities.yaml",
        f"BOX_CONFIG={host_root}/box-config",
        f"AWS_SHARED_CREDENTIALS_FILE={aws_credentials_file}",
        f"ATTEST_SECRET={host_root}/secrets/attest.secret",
    ]) + "\n"

    scheme = env["auth"]["scheme"]
    if scheme == "access-code":
        gate_auth = {"scheme": "access-code",
                     "access_list": f"{_CONTAINER_ROOT}/box-config/access.csv"}
    elif scheme == "none":
        gate_auth = {"scheme": "none"}
    else:
        raise ValueError(f"unknown auth scheme: {scheme!r}")

    exposed = set(env["exposed_asks"])
    for rname, rpolicy in env["roles"].items():
        extra = set(rpolicy.get("asks", [])) - exposed
        if extra:
            raise ValueError(
                f"role {rname!r} authorizes asks not exposed by the box: "
                f"{sorted(extra)} — role.asks must be a subset of exposed_asks")

    # gate.yaml is read INSIDE the gate container → fixed container paths.
    gate = {
        "upstream": "http://serve:8787",
        "ledger": f"{_CONTAINER_ROOT}/ledger.jsonl",
        "exposed_asks": env["exposed_asks"],
        "auth": gate_auth,
        "roles": env["roles"],
        "default_role": env["default_role"],
        "window": env["window"],
        "rate_limit": env["rate_limit"],
    }
    return dotenv, gate


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("usage: python -m corpus_server.compile <target-name> <env> "
              "[--grove-origins URL,URL] [--aws-credentials PATH] [--host-root PATH] "
              "[--out DIR]", file=sys.stderr)
        return 1
    name, env_name = argv[0], argv[1]
    from cli.infra.box_layout import box_layout
    grove_origins = _opt(argv, "--grove-origins", required=True).split(",")
    aws_creds = _opt(argv, "--aws-credentials", default="/run/secrets/aws")
    host_root = _opt(argv, "--host-root", required=True)
    out = Path(_opt(argv, "--out", default="infrastructure/corpus-server"))

    target = yaml.safe_load(
        Path(f"infrastructure/targets/{name}.yaml").read_text())
    if target.get("stack") != "corpus-server":
        raise ValueError(f"{name}: target is not a corpus-server stack")
    if env_name not in target["environments"]:
        raise ValueError(f"{name}: no environment {env_name!r}")
    env = target["environments"][env_name]

    dotenv, gate = render(env, grove_origins=grove_origins,
                          aws_credentials_file=aws_creds, host_root=host_root,
                          sites_dir=box_layout({"path": host_root})["sites"])
    out.mkdir(parents=True, exist_ok=True)
    (out / ".env").write_text(dotenv)
    (out / "gate.yaml").write_text(yaml.dump(gate, sort_keys=False))
    print(f"wrote {out/'.env'} and {out/'gate.yaml'}")
    return 0


def _opt(argv, flag, *, default=None, required=False):
    if flag in argv:
        return argv[argv.index(flag) + 1]
    if required:
        raise ValueError(f"missing {flag}")
    return default


if __name__ == "__main__":
    sys.exit(main())
