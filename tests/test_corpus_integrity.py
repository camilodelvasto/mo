"""The sidecar checks itself: embedded checksum + custody chain at resume."""
import yaml
import pytest
from shapes.corpus.engine import identity, sidecar
from shapes.corpus.engine.errors import IntegrityError


def _doc():
    return {
        "doc_id": "3f9a21aaaaaa",
        "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "in-flight@stamp",
        "stages": [],
        "artifacts": {"meta": {"path": "./meta.yaml"}},
    }


def test_write_stamps_integrity_block(tmp_path):
    meta = tmp_path / "meta.yaml"
    sidecar.write(meta, _doc())
    doc = sidecar.read(meta)
    assert doc["integrity"]["hash"].startswith("sha256:")
    assert "at" in doc["integrity"]


def test_value_edit_detected_across_restart(tmp_path):
    meta = tmp_path / "meta.yaml"
    d = _doc()
    d["stages"] = [{"id": "assert", "fields": {"consent": "given"}}]
    sidecar.write(meta, d)
    sidecar._written.clear()                 # simulate a fresh engine session
    tampered = yaml.safe_load(meta.read_text())
    tampered["stages"][0]["fields"]["consent"] = "declined"   # keeps old hash
    meta.write_text(yaml.safe_dump(tampered, sort_keys=False))
    with pytest.raises(IntegrityError):
        sidecar.read_verified(meta)


def test_backdating_at_breaks_the_hash(tmp_path):
    meta = tmp_path / "meta.yaml"
    sidecar.write(meta, _doc())
    sidecar._written.clear()
    tampered = yaml.safe_load(meta.read_text())
    tampered["integrity"]["at"] = "2020-01-01T00:00:00+00:00"
    meta.write_text(yaml.safe_dump(tampered, sort_keys=False))
    with pytest.raises(IntegrityError):
        sidecar.read_verified(meta)


def test_missing_block_is_a_violation(tmp_path):
    meta = tmp_path / "meta.yaml"
    meta.write_text(yaml.safe_dump(_doc(), sort_keys=False))
    with pytest.raises(IntegrityError):
        sidecar.read_verified(meta)


def test_append_restamps_and_verifies_clean(tmp_path):
    meta = tmp_path / "meta.yaml"
    sidecar.write(meta, _doc())
    sidecar.append(meta, {"id": "received", "fields": {}})
    sidecar._written.clear()
    doc = sidecar.read_verified(meta)        # cross-session clean read
    assert [e["id"] for e in doc["stages"]] == ["received"]


def _pair_with_chain(tmp_path):
    pair = tmp_path / "working" / "chunk" / "aaaaaaaaaaaa"
    pair.mkdir(parents=True)
    original = pair / "a.txt"
    original.write_text("the body")
    o_hash = identity.sha256_file(original)
    doc_id = o_hash.removeprefix("sha256:")[:12]
    pair = pair.rename(pair.parent / doc_id)
    transcript = pair / "transcript.md"
    transcript.write_text("the body\n")
    t_hash = identity.sha256_file(transcript)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id,
        "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "in-flight@chunk",
        "stages": [
            {"id": "received", "hash": o_hash, "fields": {}},
            {"id": "normalize",
             "input": {"artifact": "original", "hash": o_hash},
             "output": {"artifact": "transcript", "hash": t_hash},
             "fields": {}},
        ],
        "artifacts": {
            "meta": {"path": "./meta.yaml"},
            "original": {"path": "./a.txt", "kept": True},
            "transcript": {"path": "./transcript.md"},
        },
    })
    return pair


def test_verify_chain_passes_on_intact_pair(tmp_path):
    pair = _pair_with_chain(tmp_path)
    sidecar.verify_chain(pair)               # no raise


def test_verify_chain_catches_edited_artifact(tmp_path):
    pair = _pair_with_chain(tmp_path)
    (pair / "transcript.md").write_text("doctored\n")
    with pytest.raises(IntegrityError):
        sidecar.verify_chain(pair)


def test_verify_chain_catches_broken_link(tmp_path):
    pair = _pair_with_chain(tmp_path)
    doc = sidecar.read(pair / "meta.yaml")
    doc["stages"][1]["input"]["hash"] = "sha256:" + "0" * 64
    sidecar.write(pair / "meta.yaml", doc)   # engine-stamped, chain still lies
    with pytest.raises(IntegrityError):
        sidecar.verify_chain(pair)


def test_verify_chain_catches_swapped_original(tmp_path):
    pair = _pair_with_chain(tmp_path)
    (pair / "a.txt").write_text("different bytes")
    with pytest.raises(IntegrityError):
        sidecar.verify_chain(pair)
