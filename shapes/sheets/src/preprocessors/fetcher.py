"""Shared URL fetcher with browser-like headers.

Every preprocessor that fetches pages should use this instead of
requests.get() directly. Sites block default Python user agents.
"""

import requests

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def fetch(url: str, timeout: int = 30) -> str:
    """Fetch a URL with browser-like headers. Returns HTML."""
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text
