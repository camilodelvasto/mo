from dataclasses import dataclass


@dataclass
class InferenceResult:
    data: dict | None
    backend: str
    model: str
    latency_ms: int
    error: str | None
    raw_response: str
