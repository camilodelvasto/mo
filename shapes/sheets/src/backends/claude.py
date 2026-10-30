import json
import subprocess
import time

from shapes.sheets.src.backends.json_extract import extract_json
from shapes.sheets.src.types import InferenceResult


def complete(
    prompt: str,
    json_schema: dict,
    model: str = "default",
) -> InferenceResult:
    schema_instruction = (
        f"\n\nReturn ONLY valid JSON matching this schema:\n{json.dumps(json_schema)}"
    )
    full_prompt = prompt + schema_instruction

    start = time.monotonic()
    raw = ""
    try:
        result = subprocess.run(
            ["claude", "-p", full_prompt],
            capture_output=True, text=True, timeout=120,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        raw = result.stdout.strip()

        if result.returncode != 0:
            return InferenceResult(
                data=None, backend="claude", model=model,
                latency_ms=elapsed, error=f"Exit code {result.returncode}: {result.stderr}",
                raw_response=raw,
            )

        data = extract_json(raw)
        return InferenceResult(
            data=data, backend="claude", model=model,
            latency_ms=elapsed, error=None, raw_response=raw,
        )
    except json.JSONDecodeError as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return InferenceResult(
            data=None, backend="claude", model=model,
            latency_ms=elapsed, error=f"JSON parse error: {e}",
            raw_response=raw,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return InferenceResult(
            data=None, backend="claude", model=model,
            latency_ms=elapsed, error="Timeout after 120s", raw_response="",
        )
