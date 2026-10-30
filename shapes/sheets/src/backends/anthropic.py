import json
import os
import time

import requests

from shapes.sheets.src.backends.json_extract import extract_json
from shapes.sheets.src.types import InferenceResult

API_URL = "https://api.anthropic.com/v1/messages"


def complete(
    prompt: str,
    json_schema: dict,
    model: str = "claude-sonnet-4-20250514",
) -> InferenceResult:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    schema_instruction = (
        f"\n\nReturn ONLY valid JSON matching this schema:\n{json.dumps(json_schema)}"
    )

    start = time.monotonic()
    try:
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt + schema_instruction}],
            },
            timeout=120,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        body = resp.json()
        raw = body["content"][0]["text"]

        data = extract_json(raw)
        return InferenceResult(
            data=data, backend="anthropic", model=model,
            latency_ms=elapsed, error=None, raw_response=raw,
        )
    except (json.JSONDecodeError, KeyError) as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return InferenceResult(
            data=None, backend="anthropic", model=model,
            latency_ms=elapsed, error=str(e), raw_response=raw if "raw" in dir() else "",
        )
    except requests.RequestException as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return InferenceResult(
            data=None, backend="anthropic", model=model,
            latency_ms=elapsed, error=str(e), raw_response="",
        )
