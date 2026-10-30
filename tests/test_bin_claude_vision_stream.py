# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
import base64
import json
import subprocess
import sys
from pathlib import Path

BIN = [sys.executable, str(Path("bin/claude-bedrock-vision-stream")),
       "--model", "m", "--region", "eu-central-1", "--max-tokens", "64"]

ENVELOPE = {"system": "sys", "messages": [
    {"role": "user", "content": [
        {"type": "text", "text": "hi"},
        {"type": "image", "media_type": "image/webp",
         "data": base64.b64encode(b"webpbytes").decode()}]}]}

def test_maps_envelope_to_bedrock_and_streams(monkeypatch, tmp_path):
    # A fake boto3 injected via PYTHONPATH so the wrapper's `import boto3` picks it up.
    fake = tmp_path / "boto3.py"
    fake.write_text(
        "def client(*a, **k):\n"
        "    class C:\n"
        "        def converse_stream(self, **kw):\n"
        "            assert kw['system'] == [{'text': 'sys'}]\n"
        "            msg = kw['messages'][0]['content']\n"
        "            assert msg[0] == {'text': 'hi'}\n"
        "            assert msg[1]['image']['format'] == 'webp'\n"
        "            assert msg[1]['image']['source']['bytes'] == b'webpbytes'\n"
        "            return {'stream': [\n"
        "                {'contentBlockDelta': {'delta': {'text': 'ok'}}},\n"
        "                {'metadata': {'usage': {'outputTokens': 1}}}]}\n"
        "    return C()\n")
    env = {"PYTHONPATH": str(tmp_path), "PATH": ""}
    import os
    env["PATH"] = os.environ["PATH"]
    out = subprocess.run(BIN, input=json.dumps(ENVELOPE).encode(),
                         capture_output=True, env={**os.environ, **env})
    assert out.returncode == 0, out.stderr
    events = [json.loads(l) for l in out.stdout.decode().splitlines() if l.strip()]
    assert {"event": "token", "text": "ok"} in events
    assert events[-1]["event"] == "done"
