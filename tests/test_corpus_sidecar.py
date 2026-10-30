import yaml
import pytest
from shapes.corpus.engine import sidecar
from shapes.corpus.engine.errors import SidecarError, IntegrityError


def _doc():
    return {
        "doc_id": "3f9a21aaaaaa",
        "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "in-flight@stamp",
        "stages": [],
        "artifacts": {"meta": {"path": "./meta.yaml"}},
    }


def test_write_then_read_roundtrip(tmp_path):
    meta = tmp_path / "meta.yaml"
    sidecar.write(meta, _doc())
    assert sidecar.read(meta)["doc_id"] == "3f9a21aaaaaa"


def test_write_is_atomic_no_temp_left_behind(tmp_path):
    meta = tmp_path / "meta.yaml"
    sidecar.write(meta, _doc())
    assert [p.name for p in tmp_path.iterdir()] == ["meta.yaml"]


def test_append_adds_one_entry(tmp_path):
    meta = tmp_path / "meta.yaml"
    sidecar.write(meta, _doc())
    doc = sidecar.append(meta, {"id": "received", "fields": {"visibility": "private"}})
    assert [e["id"] for e in doc["stages"]] == ["received"]
    assert sidecar.read(meta)["stages"][0]["fields"]["visibility"] == "private"


def test_torn_file_throws(tmp_path):
    meta = tmp_path / "meta.yaml"
    meta.write_text("doc_id: [unclosed")
    with pytest.raises(SidecarError):
        sidecar.read(meta)


def test_foreign_write_detected(tmp_path):
    meta = tmp_path / "meta.yaml"
    sidecar.write(meta, _doc())
    sidecar.read_verified(meta)  # engine's own write: fine
    foreign = yaml.safe_load(meta.read_text())
    foreign["stages"].append({"id": "smuggled", "fields": {"consent": "given"}})
    meta.write_text(yaml.safe_dump(foreign))  # a human edits the sidecar
    with pytest.raises(IntegrityError):
        sidecar.read_verified(meta)
