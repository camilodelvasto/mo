"""FETCH preprocessor — fetches a URL, extracts JSON-LD and text.

Three-stage fetch, controlled by the browser: declaration on the pipeline input:
1. Static fetch with browser headers (fast, ~200ms)
2. If no content: Playwright headless (browser: headless, ~3s, renders JS)
3. If still no content: Playwright visible (browser: visible, user solves CAPTCHA)

The browser: setting is declared in sheet.yaml on the pipeline input:
  FETCH:
    preprocess: trafilatura
    browser: visible    # headless | visible | none
"""

import json
import logging
import re
import time

import trafilatura

from shapes.sheets.src.preprocessors.fetcher import fetch

log = logging.getLogger("sheets.fetch")


def preprocess(url: str, browser: str = "headless") -> str:
    """Fetch URL, extract JSON-LD + text, return combined prompt input.

    browser: "none" — static only, "headless" — Playwright fallback,
    "visible" — user-assisted browser for CAPTCHA sites.
    """
    # Stage 1: static fetch — when a browser is declared, content must meet
    # MIN_CONTENT_LENGTH to be accepted; thin pages are shell/JS loaders.
    try:
        html = fetch(url)
        combined = _extract_content(html)
        if combined and (browser == "none" or len(combined) >= MIN_CONTENT_LENGTH):
            return combined
        if combined:
            log.info("Static fetch returned thin content (%d chars), escalating to %s", len(combined), browser)
    except Exception as e:
        log.info("Static fetch failed for %s: %s", url, e)

    if browser == "none":
        raise ValueError(f"Could not extract content from {url} (static fetch only)")

    if browser == "visible":
        # Declaration says this site needs a visible browser — skip headless
        log.info("Opening visible browser for %s", url)
        html = _fetch_with_playwright(url, headless=False, wait_for_content=True)
        combined = _extract_content(html)
        if combined:
            return combined
        raise ValueError(f"Could not extract content from {url} (visible browser failed)")

    # browser == "headless"
    log.info("Trying Playwright headless for %s", url)
    html = _fetch_with_playwright(url, headless=True)
    combined = _extract_content(html)
    if combined:
        return combined

    raise ValueError(f"Could not extract content from {url} (headless failed)")


MIN_CONTENT_LENGTH = 500  # Real listing pages have thousands of chars


def _fetch_with_playwright(
    url: str,
    headless: bool = True,
    wait_for_content: bool = False,
) -> str:
    """Fetch a URL using Chromium.

    headless=False opens a visible browser window.
    wait_for_content=True polls until substantial content appears
    (user solves CAPTCHA, page loads real content, browser auto-closes).
    Content must exceed MIN_CONTENT_LENGTH to be considered real —
    navigation chrome, loading spinners, and CAPTCHA pages are shorter.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        if wait_for_content:
            # Wait for page to fully render before polling
            page.wait_for_timeout(8000)

            # Poll until substantial content appears — max 120s
            html = ""
            for _ in range(120):
                try:
                    html = page.content()
                except Exception:
                    # Page is navigating (e.g., CAPTCHA redirect) — wait and retry
                    page.wait_for_timeout(1000)
                    continue
                content = _extract_content(html)
                if content and len(content) > MIN_CONTENT_LENGTH:
                    log.info("Content detected (%d chars) — closing browser", len(content))
                    break
                page.wait_for_timeout(1000)
            else:
                try:
                    html = page.content()
                except Exception:
                    pass
        else:
            page.wait_for_timeout(3000)
            html = page.content()

        browser.close()
    return html


def _extract_content(html: str) -> str | None:
    """Extract JSON-LD + text from HTML. Returns None if nothing found."""
    jsonld_blocks = _extract_jsonld(html)
    text = trafilatura.extract(html) or ""

    parts = []
    if jsonld_blocks:
        parts.append("Structured data from page:")
        for block in jsonld_blocks:
            parts.append(json.dumps(block, ensure_ascii=False, indent=2))
        parts.append("")

    if text:
        parts.append("Page text:")
        parts.append(text)

    combined = "\n".join(parts)
    return combined if combined.strip() else None


def _extract_jsonld(html: str) -> list[dict]:
    """Extract JSON-LD blocks from HTML."""
    blocks = []
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        try:
            data = json.loads(match.group(1).strip())
            blocks.append(data)
        except (json.JSONDecodeError, TypeError):
            continue
    return blocks
