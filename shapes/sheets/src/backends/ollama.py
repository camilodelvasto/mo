import json
import time

import requests

from shapes.sheets.src.types import InferenceResult

ENDPOINT = "http://localhost:11434/api/generate"


def complete(
    prompt: str,
    json_schema: dict,
    model: str = "qwen3:8b",
    endpoint: str = ENDPOINT,
) -> InferenceResult:
    start = time.monotonic()
    try:
        resp = requests.post(
            endpoint,
            json={
                "model": model,
                "prompt": prompt,
                "format": json_schema,
                "stream": False,
            },
            timeout=120,
        )
        raw = resp.json().get("response", "")
        elapsed = int((time.monotonic() - start) * 1000)
        data = json.loads(raw)
        return InferenceResult(
            data=data, backend="ollama", model=model,
            latency_ms=elapsed, error=None, raw_response=raw,
        )
    except (json.JSONDecodeError, KeyError) as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return InferenceResult(
            data=None, backend="ollama", model=model,
            latency_ms=elapsed, error=str(e), raw_response=raw if "raw" in dir() else "",
        )
    except requests.RequestException as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return InferenceResult(
            data=None, backend="ollama", model=model,
            latency_ms=elapsed, error=str(e), raw_response="",
        )
