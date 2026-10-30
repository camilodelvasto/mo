# tests/test_bin_anonymize_llm.py — the wrapper against a fake ollama: the
# model's answer is canned, so what is under test is the contract (argv, the
# span check, trimming, document-wide replacement, failing closed).
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

BIN = [sys.executable, str(Path("bin/anonymize-llm"))]


class _Fake:
    """Serves /api/chat; `answers` is popped per request (a dict → JSON
    content, a str → raw content, an int → that HTTP status)."""
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.prompts.append(body)
                ans = outer.answers.pop(0)
                if isinstance(ans, int):
                    self.send_response(ans); self.end_headers(); return
                done_reason = "stop"
                if isinstance(ans, tuple):            # ("length", partial content)
                    done_reason, ans = ans
                content = json.dumps(ans) if isinstance(ans, dict) else ans
                out = json.dumps({"message": {"role": "assistant", "content": content},
                                  "done_reason": done_reason}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.host = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


def _run(fake, text, redact="names,contacts,ids", segment=6000):
    return subprocess.run(BIN + ["--model", "m", "--host", fake.host, "--redact", redact,
                                 "--segment-chars", str(segment), "--num-ctx", "8192",
                                 "--num-predict", "512"],
                          input=text.encode(), capture_output=True)


TEXT = ("# ENTREVISTA_PEDRO_PABLO_SALAS\n\nGracias, Pedro Pablo Salas. "
        "Dime Pepe. la señora vargas. Correo pepe@x.co, celular 300 123 4567.\n"
        "Mario Salas Prieto y mario. Ya [NOMBRE] dijo.\n")


def test_spans_are_replaced_document_wide_case_insensitively_across_underscores():
    fake = _Fake([{"spans": [
        {"text": "# ENTREVISTA_PEDRO_PABLO_SALAS", "kind": "names"},   # marker dragged in
        {"text": "Pedro Pablo Salas", "kind": "names"},
        {"text": "Pepe", "kind": "names"},
        {"text": "Vargas", "kind": "names"},                               # text has "vargas"
        {"text": "pepe@x.co,", "kind": "contacts"},                      # trailing comma
        {"text": "300 123 4567", "kind": "contacts"},
        {"text": "Mario Salas Prieto", "kind": "names"},
        {"text": "Mario", "kind": "names"},
        {"text": "[NOMBRE]", "kind": "names"},                            # placeholder: skipped
    ]}])
    try:
        r = _run(fake, TEXT)
    finally:
        fake.stop()
    assert r.returncode == 0, r.stderr
    out = r.stdout.decode()
    assert out.splitlines()[0] == "# [NOMBRE]"                  # heading marker survives
    assert "[NOMBRE] y [NOMBRE]. Ya [NOMBRE] dijo." in out       # lowercase mario, placeholder intact
    assert "Correo [CONTACTO], celular [CONTACTO]." in out
    assert "la señora [NOMBRE]." in out
    for leak in ("Pedro", "Salas", "Pepe", "vargas", "pepe@x.co", "300", "Mario", "mario"):
        assert leak not in out, leak
    assert "Gracias, [NOMBRE]. Dime [NOMBRE]." in out


def test_a_kind_not_requested_is_left_alone():
    fake = _Fake([{"spans": [{"text": "Bogotá", "kind": "places"},
                             {"text": "Ana", "kind": "names"}]}])
    try:
        r = _run(fake, "Ana vive en Bogotá.\n", redact="names")
    finally:
        fake.stop()
    assert r.returncode == 0 and r.stdout.decode() == "[NOMBRE] vive en Bogotá.\n"


def test_long_text_is_segmented_on_newlines_and_spans_apply_everywhere():
    text = "Ana habla.\n" * 50          # 11-char lines, cap 100 → 9 lines a segment → 6 segments
    answers = [{"spans": []}] * 5 + [{"spans": [{"text": "Ana", "kind": "names"}]}]
    fake = _Fake(answers)
    try:
        r = _run(fake, text, segment=100)
    finally:
        fake.stop()
    assert r.returncode == 0
    assert len(fake.prompts) == 6
    assert all(p["options"]["num_ctx"] == 8192 and p["options"]["num_predict"] == 512
               and p["think"] is False for p in fake.prompts)
    assert r.stdout.decode() == "[NOMBRE] habla.\n" * 50     # found once, gone everywhere


def test_a_span_not_in_the_text_fails_closed():
    fake = _Fake([{"spans": [{"text": "Zutano", "kind": "names"}]}])
    try:
        r = _run(fake, "Ana habla.\n")
    finally:
        fake.stop()
    assert r.returncode == 1 and b"not in the text" in r.stderr and r.stdout == b""


def test_a_non_contract_answer_fails_closed():
    fake = _Fake(["I cannot help with that."])
    try:
        r = _run(fake, "Ana habla.\n")
    finally:
        fake.stop()
    assert r.returncode == 1 and b"span contract" in r.stderr and r.stdout == b""


def test_host_down_fails_closed():
    r = subprocess.run(BIN + ["--model", "m", "--host", "http://127.0.0.1:9", "--redact", "names",
                              "--segment-chars", "100", "--num-ctx", "8192", "--num-predict", "512"],
                       input=b"Ana.\n", capture_output=True)
    assert r.returncode == 1 and b"ollama at" in r.stderr and r.stdout == b""


def test_unknown_kind_and_missing_args_are_refused():
    r = subprocess.run(BIN + ["--model", "m", "--host", "h", "--redact", "faces",
                              "--segment-chars", "100", "--num-ctx", "8192", "--num-predict", "512"],
                       input=b"", capture_output=True)
    assert r.returncode != 0 and b"unknown kind" in r.stderr
    r = subprocess.run(BIN + ["--model", "m", "--host", "h", "--redact", "names"], input=b"", capture_output=True)
    assert r.returncode != 0 and b"--segment-chars" in r.stderr


def test_markdown_escaped_underscores_match_the_unescaped_span():
    fake = _Fake([{"spans": [{"text": "ENTREVISTA_JUAN_PEREZ", "kind": "names"},
                             {"text": "Juan Perez", "kind": "names"}]}])
    try:
        r = _run(fake, "# ENTREVISTA\\_JUAN\\_PEREZ\n\nHabla Juan Perez.\n")
    finally:
        fake.stop()
    assert r.returncode == 0, r.stderr
    assert r.stdout.decode() == "# [NOMBRE]\n\nHabla [NOMBRE].\n"


def test_an_answer_that_hit_the_generation_cap_bisects_the_segment():
    # 20 lines, cap 400 → one segment of 20 lines (18 chars each = 360). The
    # looped answer makes the wrapper split it at the middle newline and ask
    # for each half; both halves answer normally.
    text = "".join(f"Ana dice algo {i:02d}.\n" for i in range(20))
    fake = _Fake([("length", '{"spans": [{"text": "Ana", "kind": "names"}, {"text": "Ana", "ki'),
                  {"spans": [{"text": "Ana", "kind": "names"}]},
                  {"spans": []}])
    try:
        r = _run(fake, text, segment=400)
    finally:
        fake.stop()
    assert r.returncode == 0, r.stderr
    assert len(fake.prompts) == 3
    halves = [p["messages"][0]["content"].split("Segment:\n", 1)[1] for p in fake.prompts[1:]]
    assert "".join(halves) == text                       # the halves ARE the segment
    assert all(h.endswith("\n") for h in halves)        # split on a line break
    assert r.stdout.decode() == "".join(f"[NOMBRE] dice algo {i:02d}.\n" for i in range(20))


def test_a_segment_that_keeps_looping_below_the_floor_fails_closed():
    text = "Ana.\n" * 4                                  # 20 chars: already under the floor
    fake = _Fake([("length", "{")])
    try:
        r = _run(fake, text, segment=400)
    finally:
        fake.stop()
    assert r.returncode == 1 and b"generation cap" in r.stderr and r.stdout == b""
