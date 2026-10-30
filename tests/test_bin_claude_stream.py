# tests/test_bin_claude_stream.py
# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import json, subprocess, sys
from pathlib import Path

WRAP = Path("bin/claude-stream")

def _run(stub_out: str):
    """Run the wrapper with `claude` replaced by a stub that prints stub_out."""
    stub = "\n".join([
        "#!/usr/bin/env python3",
        "import sys",
        f"sys.stdout.write({stub_out!r})",
    ])
    import os, tempfile
    d = tempfile.mkdtemp()
    (Path(d) / "claude").write_text(stub)
    (Path(d) / "claude").chmod(0o755)
    env = {**os.environ, "PATH": d + ":" + os.environ["PATH"]}
    return subprocess.run([sys.executable, str(WRAP), "--model", "m"],
                          input=b"prompt", capture_output=True, env=env)

def test_streams_token_then_done():
    stub_out = "\n".join([
        json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "ho"}}}),
        json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "la"}}}),
        json.dumps({"type": "result", "subtype": "success", "result": "hola",
                    "total_cost_usd": 0.01, "duration_ms": 5,
                    "usage": {"input_tokens": 1, "output_tokens": 2,
                              "cache_read_input_tokens": 0},
                    "modelUsage": {"claude-opus-4-8": {}}}),
    ]) + "\n"
    proc = _run(stub_out)
    assert proc.returncode == 0, proc.stderr.decode()
    events = [json.loads(l) for l in proc.stdout.decode().splitlines() if l.strip()]
    tokens = [e["text"] for e in events if e["event"] == "token"]
    done = [e for e in events if e["event"] == "done"]
    assert "".join(tokens) == "hola"
    assert done and done[0]["model"] == "claude-opus-4-8"
    assert done[0]["cost_usd"] == 0.01
    assert done[0]["usage"]["output_tokens"] == 2

def test_error_line_becomes_error_event():
    stub_out = json.dumps({"type": "result", "is_error": True,
                           "result": "boom"}) + "\n"
    proc = _run(stub_out)
    assert proc.returncode == 1
    events = [json.loads(l) for l in proc.stdout.decode().splitlines() if l.strip()]
    assert events[-1]["event"] == "error"
    assert events[-1]["kind"] == "synthesis_failed"
