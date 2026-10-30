# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The one canonical origin function, used both ways: the resolver derives the
CSP connect-src origin from the ask endpoint, and the deploy probe derives the
allowed origin from the grove's base_url. The browser's same-origin check is
byte-exact on scheme-host-port, so this canonicalizes once — lowercase host,
drop the default port, no path, no trailing slash — and every comparison runs on
two of its outputs."""
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        raise ValueError(f"not an absolute URL with a host: {url!r}")
    scheme = parts.scheme.lower()
    host = parts.hostname.lower()
    port = parts.port
    if port is None or port == _DEFAULT_PORTS.get(scheme):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"
