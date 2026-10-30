import hashlib
from shapes.corpus.engine import identity, sidecar


def test_sha256_file_prefixed(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert identity.sha256_file(f) == f"sha256:{expected}"


def test_doc_id_is_first_12_hex(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    assert identity.doc_id_for(f) == hashlib.sha256(b"hello").hexdigest()[:12]


def _make_pair(corpus_dir, area, doc_id):
    pair = corpus_dir / area / doc_id
    pair.mkdir(parents=True)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": "x", "stages": [], "artifacts": {},
    })
    return pair


def test_find_pair_searches_every_area(tmp_path):
    a = _make_pair(tmp_path, "working/datasheet", "aaaaaaaaaaaa")
    b = _make_pair(tmp_path, "corpus", "bbbbbbbbbbbb")
    assert identity.find_pair(tmp_path, "aaaaaaaaaaaa") == a / "meta.yaml"
    assert identity.find_pair(tmp_path, "bbbbbbbbbbbb") == b / "meta.yaml"
    assert identity.find_pair(tmp_path, "cccccccccccc") is None


def test_iter_pairs_yields_metas_per_area(tmp_path):
    _make_pair(tmp_path, "working/stamp", "aaaaaaaaaaaa")
    _make_pair(tmp_path, "failed/normalize", "bbbbbbbbbbbb")
    _make_pair(tmp_path, "corpus", "cccccccccccc")
    found = {p.parent.name for p in identity.iter_pairs(tmp_path, ["working", "failed"])}
    assert found == {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}


def test_find_orphans_clean_tree_is_empty(tmp_path):
    """A well-formed corpus has no orphans."""
    _make_pair(tmp_path, "working/stamp", "aaaaaaaaaaaa")
    _make_pair(tmp_path, "corpus", "bbbbbbbbbbbb")
    assert identity.find_orphans(tmp_path) == []


def test_find_orphans_detects_missing_sidecar(tmp_path):
    """A directory under working/stamp/ without meta.yaml is a missing-sidecar orphan."""
    pair_dir = tmp_path / "working" / "stamp" / "cccccccccccc"
    pair_dir.mkdir(parents=True)
    # no meta.yaml written
    findings = identity.find_orphans(tmp_path)
    assert len(findings) == 1
    assert findings[0]["kind"] == "missing-sidecar"
    assert findings[0]["pair_dir"] == pair_dir


def test_find_orphans_detects_missing_file(tmp_path):
    """A sidecar whose manifest names ./transcript.md but that file is gone
    is a missing-file orphan. The meta artifact itself is skipped."""
    pair = _make_pair(tmp_path, "working/stamp", "dddddddddddd")
    # patch the sidecar to reference a non-existent file
    doc = sidecar.read(pair / "meta.yaml")
    doc["artifacts"]["transcript"] = {"path": "./transcript.md"}
    sidecar.write(pair / "meta.yaml", doc)
    findings = identity.find_orphans(tmp_path)
    assert len(findings) == 1
    f = findings[0]
    assert f["kind"] == "missing-file"
    assert f["path"] == "./transcript.md"
    assert f["meta"] == pair / "meta.yaml"
