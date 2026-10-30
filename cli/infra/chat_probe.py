# cli/infra/chat_probe.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The reverse-origin + code agreement check, made load-bearing: one real authed
request from the grove's origin to the box, converting the two untraceable browser
failures (wrong CORS origin, wrong access code) into a deploy-time error. Three
distinct outcomes so the operator is sent to the right fix, never the likeliest."""
import sys
import urllib.error
import urllib.request


class ProbeError(Exception):
    pass


def probe_chat(check_url: str, grove_origin: str, code: str, *, timeout: int = 30) -> None:
    req = urllib.request.Request(check_url, data=b"", method="POST", headers={
        "Origin": grove_origin,
        "Authorization": f"Bearer {code}"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        status = resp.status
        acao = resp.headers.get("Access-Control-Allow-Origin")
    except urllib.error.HTTPError as e:                       # box answered, non-2xx
        if e.code == 401:
            raise ProbeError(
                f"the box rejected the injected code (401) — it does not match a "
                f"row in the box's access.csv")
        acao = e.headers.get("Access-Control-Allow-Origin")
        status = e.code
    except urllib.error.URLError as e:                        # couldn't reach / TLS / dns
        raise ProbeError(
            f"could not get a usable answer from the box at {check_url} ({e.reason})")

    if acao == "*":
        print(f"  warning: the box allows ALL origins (Access-Control-Allow-Origin: *) — "
              f"your origin works, but the reverse agreement isn't enforced by the box",
              file=sys.stdout)
    elif acao != grove_origin:
        raise ProbeError(
            f"the box allows {acao}, not this grove's origin {grove_origin}; "
            f"add it to the stack target's grove_origins and redeploy the stack")
    if status != 204:
        raise ProbeError(
            f"could not get a usable answer from the box at {check_url} (status {status})")
