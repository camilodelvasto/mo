# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""bin/claude-vision-stream — the LOCAL twin of claude-bedrock-vision-stream: the
engine's multimodal envelope → the Claude CLI's stream-json input → the same NDJSON
every stream binding emits. Runs anywhere `claude` is installed; no AWS."""
import json, os, subprocess, sys, tempfile
from pathlib import Path

WRAP = Path(__file__).resolve().parents[1] / "bin" / "claude-vision-stream"

ENVELOPE = {
    "system": "sys",
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": "first"},
                                     {"type": "image", "media_type": "image/webp", "data": "aW1n"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "earlier answer"}]},
        {"role": "user", "content": [{"type": "text", "text": "now?"}]},
    ]}


def _run(stub_out: str, capture: Path):
    """`claude` replaced by a stub that records argv + stdin and prints stub_out."""
    d = tempfile.mkdtemp()
    stub = "\n".join([
        "#!/usr/bin/env python3",
        "import sys, json",
        f"open({str(capture)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], 'stdin': sys.stdin.read()}}))",
        f"sys.stdout.write({stub_out!r})"])
    (Path(d) / "claude").write_text(stub); (Path(d) / "claude").chmod(0o755)
    env = {**os.environ, "PATH": d + ":" + os.environ["PATH"]}
    return subprocess.run([sys.executable, str(WRAP), "--model", "m"],
                          input=json.dumps(ENVELOPE).encode(), capture_output=True, env=env)


def _ok_stream():
    return "\n".join([
        json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "red"}}}),
        json.dumps({"type": "result", "subtype": "success", "result": "red",
                    "total_cost_usd": 0.02, "usage": {"input_tokens": 3, "output_tokens": 1,
                    "cache_read_input_tokens": 0}, "modelUsage": {"claude-haiku-4-5": {}}}),
    ]) + "\n"


def test_envelope_becomes_one_stream_json_user_turn_with_the_images(tmp_path):
    cap = tmp_path / "cap.json"
    proc = _run(_ok_stream(), cap)
    assert proc.returncode == 0, proc.stderr.decode()
    rec = json.loads(cap.read_text())
    argv = rec["argv"]
    assert argv[:2] == ["-p", "--model"] and argv[2] == "m"
    assert "--input-format" in argv and argv[argv.index("--input-format") + 1] == "stream-json"
    assert argv[argv.index("--system-prompt") + 1] == "sys"
    turns = [json.loads(l) for l in rec["stdin"].splitlines() if l.strip()]
    assert len(turns) == 1 and turns[0]["type"] == "user"          # one turn → one generation
    content = turns[0]["message"]["content"]
    images = [b for b in content if b["type"] == "image"]
    assert images == [{"type": "image", "source": {"type": "base64", "media_type": "image/webp", "data": "aW1n"}}]
    text = "".join(b["text"] for b in content if b["type"] == "text")
    assert "first" in text and "earlier answer" in text and text.rstrip().endswith("now?")
    assert "Conversación" not in text, "a machine binding carries no language of its own"
    events = [json.loads(l) for l in proc.stdout.decode().splitlines() if l.strip()]
    assert [e["text"] for e in events if e["event"] == "token"] == ["red"]
    assert events[-1]["event"] == "done" and events[-1]["model"] == "claude-haiku-4-5"


def test_bad_envelope_is_a_named_error(tmp_path):
    d = tempfile.mkdtemp()
    (Path(d) / "claude").write_text("#!/bin/sh\nexit 0\n"); (Path(d) / "claude").chmod(0o755)
    proc = subprocess.run([sys.executable, str(WRAP), "--model", "m"], input=b"not json",
                          capture_output=True, env={**os.environ, "PATH": d + ":" + os.environ["PATH"]})
    assert proc.returncode == 1
    last = json.loads(proc.stdout.decode().splitlines()[-1])
    assert last["event"] == "error" and last["kind"] == "synthesis_failed"


def test_cli_error_result_is_an_error_event(tmp_path):
    proc = _run(json.dumps({"type": "result", "is_error": True, "result": "boom"}) + "\n",
                tmp_path / "cap.json")
    assert proc.returncode == 1
    last = json.loads(proc.stdout.decode().splitlines()[-1])
    assert last["event"] == "error" and last["kind"] == "synthesis_failed"


def test_the_history_label_is_a_binding_argument(tmp_path):
    """How prior turns are introduced is content, not transport: the ask's language
    lives in the corpus, so the wrapper takes the label as an argument."""
    cap = tmp_path / "cap.json"
    d = tempfile.mkdtemp()
    stub = "\n".join([
        "#!/usr/bin/env python3", "import sys, json",
        f"open({str(cap)!r}, 'w').write(json.dumps({{'stdin': sys.stdin.read()}}))",
        f"sys.stdout.write({_ok_stream()!r})"])
    (Path(d) / "claude").write_text(stub); (Path(d) / "claude").chmod(0o755)
    env = {**os.environ, "PATH": d + ":" + os.environ["PATH"]}
    proc = subprocess.run([sys.executable, str(WRAP), "--model", "m", "--history-label", "Conversación previa:"],
                          input=json.dumps(ENVELOPE).encode(), capture_output=True, env=env)
    assert proc.returncode == 0, proc.stderr.decode()
    turn = json.loads(json.loads(cap.read_text())["stdin"].splitlines()[0])
    text = "".join(b["text"] for b in turn["message"]["content"] if b["type"] == "text")
    assert text.startswith("Conversación previa:")
