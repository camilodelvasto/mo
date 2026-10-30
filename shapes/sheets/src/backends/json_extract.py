"""Shared JSON extraction from LLM responses.

LLMs return JSON wrapped in code fences, prose, or other text.
This module extracts the first valid JSON object regardless of
surrounding content.
"""

import json
import re


def extract_json(text: str) -> dict:
    """Extract the first JSON object from text.

    Tries in order:
    1. Markdown code fence (```json ... ```)
    2. First { ... } brace-matched block
    Raises json.JSONDecodeError if nothing parseable is found.
    """
    # Try markdown code fence first
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1).strip())

    # Find first JSON object by brace matching
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)

    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise json.JSONDecodeError("Unterminated JSON object", text, start)
