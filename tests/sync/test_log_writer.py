import json
from cli.sync.daemon.log_writer import LogWriter
from cli.sync.daemon.events import SyncEvent


def test_writes_jsonl(tmp_path):
    log_path = tmp_path / "sync.log"
    writer = LogWriter(log_path)
    writer.write(SyncEvent(type="push_ok", folder="content", sha="abc"))
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["type"] == "push_ok"
    assert data["folder"] == "content"
    assert data["sha"] == "abc"


def test_rotation_at_threshold(tmp_path):
    log_path = tmp_path / "sync.log"
    writer = LogWriter(log_path, max_bytes=100)
    for i in range(20):
        writer.write(SyncEvent(type="push_ok", folder="content"))
    assert (tmp_path / "sync.log.1").exists()


def test_rotation_keeps_max_generations(tmp_path):
    log_path = tmp_path / "sync.log"
    writer = LogWriter(log_path, max_bytes=50, max_generations=3)
    for i in range(100):
        writer.write(SyncEvent(type="push_ok", folder="content"))
    assert (tmp_path / "sync.log.3").exists()
    assert not (tmp_path / "sync.log.4").exists()
