import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

EMBED = Path(__file__).resolve().parents[1] / "bin" / "embed"


class _Handler(BaseHTTPRequestHandler):
    served_model = "bge-m3"

    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        n = len(body["input"])
        out = {"model": self.served_model,
               "embeddings": [[0.1, 0.2, 0.3, 0.4] for _ in range(n)]}
        self._send(out)

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def stub_ollama():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _run(stdin: str, host: str):
    return subprocess.run(
        [str(EMBED), "--model", "bge-m3", "--host", host],
        input=stdin.encode(), capture_output=True,
        env={"PATH": "/usr/bin:/bin"},
    )


def test_emits_ref_vector_pairs_in_order(stub_ollama):
    chunks = '{"ref": "aaa", "text": "hola"}\n{"ref": "bbb", "text": "mundo"}\n'
    proc = _run(chunks, stub_ollama)
    assert proc.returncode == 0, proc.stderr.decode()
    lines = [json.loads(l) for l in proc.stdout.decode().splitlines()]
    assert [l["ref"] for l in lines] == ["aaa", "bbb"]
    assert lines[0]["vector"] == [0.1, 0.2, 0.3, 0.4]
    assert lines[0]["dim"] == 4
    assert lines[0]["model"] == "bge-m3"  # ground truth from the server, not --model


def test_count_mismatch_exits_nonzero(stub_ollama, monkeypatch):
    # Force the stub to return one embedding for two chunks.
    monkeypatch.setattr(_Handler, "do_POST", lambda self: self._send({"model": "bge-m3", "embeddings": [[0.1, 0.2, 0.3, 0.4]]}))
    chunks = '{"ref": "aaa", "text": "hola"}\n{"ref": "bbb", "text": "mundo"}\n'
    proc = _run(chunks, stub_ollama)
    assert proc.returncode != 0
    assert b"count" in proc.stderr.lower() or b"mismatch" in proc.stderr.lower()
