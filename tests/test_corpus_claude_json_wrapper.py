# tests/test_corpus_claude_json_wrapper.py — the synthesis envelope adapter mapping.
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "bin" / "claude-json"
_SPEC = importlib.util.spec_from_loader("claude_json", SourceFileLoader("claude_json", str(_PATH)))
claude_json = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(claude_json)


def test_to_envelope_maps_claude_json_to_the_moui_envelope():
    claude = {
        "result": "Sí, hay apoyo. [aaaaaaaaaaaa:r1]",
        "total_cost_usd": 0.046,
        "duration_ms": 4103,
        "usage": {"input_tokens": 1234, "output_tokens": 480,
                  "cache_read_input_tokens": 21434},
        "modelUsage": {"claude-opus-4-8[1m]": {"inputTokens": 1234}},
    }
    env = claude_json.to_envelope(claude)
    assert env["answer"] == "Sí, hay apoyo. [aaaaaaaaaaaa:r1]"
    assert env["model"] == "claude-opus-4-8[1m]"
    assert env["usage"] == {"input_tokens": 1234, "output_tokens": 480,
                            "cache_read_input_tokens": 21434}
    assert env["cost_usd"] == 0.046
    assert env["duration_ms"] == 4103
