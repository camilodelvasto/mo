import yaml
import pytest
from shapes.corpus.engine import sidecar


def _corpus(tmp_path):
    corpus = tmp_path / "content" / "c"
    corpus.mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\n"
        "fields: {doc_type: {type: string, by: operator}}\n"
        "entrypoints: [{id: general, area: dropbox/general}]\n"
        "pipeline: [{id: stamp, uses: engine.stamp}]\n"
    )
    return corpus


def _pair(corpus, area, doc_id, stages, status="in-flight@x"):
    pair = corpus / area / doc_id
    pair.mkdir(parents=True)
    sidecar.write(pair / "meta.yaml", {
        "doc_id": doc_id, "flow": {"id": "t", "version": 1, "hash": "sha256:00"},
        "status": status, "stages": stages, "artifacts": {},
    })
    return pair


def test_status_counts_per_area(tmp_path, capsys):
    from shapes.corpus.commands import status
    corpus = _corpus(tmp_path)
    _pair(corpus, "working/datasheet", "aaaaaaaaaaaa", [])
    _pair(corpus, "working/datasheet", "bbbbbbbbbbbb", [])
    _pair(corpus, "failed/normalize", "cccccccccccc", [])
    _pair(corpus, "corpus", "dddddddddddd", [], status="complete")
    status.run(tmp_path, "corpus", [str(corpus)])
    out = capsys.readouterr().out
    assert "working/datasheet" in out and "2" in out
    assert "failed/normalize" in out
    assert "corpus" in out


def test_tasks_lists_parked_checklist_and_failures(tmp_path, capsys):
    from shapes.corpus.commands import tasks
    corpus = _corpus(tmp_path)
    _pair(corpus, "working/datasheet", "aaaaaaaaaaaa",
          [{"id": "datasheet", "fields": {}, "parked": ["consent", "doi"]}],
          status="parked@datasheet")
    _pair(corpus, "failed/normalize", "bbbbbbbbbbbb",
          [{"id": "normalize", "failed": "no route for mime application/zip"}],
          status="failed@normalize")
    tasks.run(tmp_path, "corpus", [str(corpus)])
    out = capsys.readouterr().out
    assert "aaaaaaaaaaaa" in out and "consent" in out and "doi" in out
    assert "bbbbbbbbbbbb" in out and "no route" in out


def test_ls_shows_projection_of_completed(tmp_path, capsys):
    from shapes.corpus.commands import ls
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa", [
        {"id": "stamp", "fields": {"size": 1024, "hash": "abc123", "mime": "text/plain"}},
        {"id": "classify", "fields": {"doc_type": "interview"}},
    ], status="complete")
    ls.run(tmp_path, "corpus", [str(corpus)])
    out = capsys.readouterr().out
    assert "aaaaaaaaaaaa" in out and "interview" in out
    assert "size=" not in out


def test_show_gives_provenance(tmp_path, capsys):
    from shapes.corpus.commands import show
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa", [
        {"id": "normalize", "fields": {"language": "de"}},
        {"id": "assert", "by": "operator", "fields": {"language": "en"}},
    ], status="complete")
    show.run(tmp_path, "corpus", [str(corpus), "aaaaaaaaaaaa"])
    out = capsys.readouterr().out
    assert "language" in out and "en" in out and "assert" in out


def test_show_unknown_doc_throws(tmp_path):
    from shapes.corpus.commands import show
    corpus = _corpus(tmp_path)
    with pytest.raises(SystemExit):
        show.run(tmp_path, "corpus", [str(corpus), "ffffffffffff"])


def test_tasks_partial_assert_shows_remaining_parked(tmp_path, capsys):
    """A pair with [datasheet parked [consent, doi], assert {doi: x}] shows
    'parked: consent' only — doi was satisfied by the assert."""
    from shapes.corpus.commands import tasks
    corpus = _corpus(tmp_path)
    _pair(corpus, "working/datasheet", "aaaaaaaaaaaa", [
        {"id": "datasheet", "fields": {}, "parked": ["consent", "doi"]},
        {"id": "assert", "by": "operator", "fields": {"doi": "10.1234/x"}},
    ], status="parked@datasheet")
    tasks.run(tmp_path, "corpus", [str(corpus)])
    out = capsys.readouterr().out
    assert "consent" in out
    assert "doi" not in out


def test_status_reports_orphans(tmp_path, capsys):
    """status output includes orphan counts when orphans are present."""
    from shapes.corpus.commands import status
    corpus = _corpus(tmp_path)
    # a pair dir without a sidecar
    orphan_dir = corpus / "working" / "stamp" / "eeeeeeeeeeee"
    orphan_dir.mkdir(parents=True)
    status.run(tmp_path, "corpus", [str(corpus)])
    out = capsys.readouterr().out
    assert "orphans: missing sidecar" in out
    assert "1" in out


def test_tasks_lists_orphan_rows(tmp_path, capsys):
    """tasks lists ORPHAN rows for missing-sidecar and missing-file findings."""
    from shapes.corpus.commands import tasks
    from shapes.corpus.engine import sidecar as sc
    corpus = _corpus(tmp_path)
    # missing-sidecar orphan
    orphan_dir = corpus / "working" / "stamp" / "ffffffffffff"
    orphan_dir.mkdir(parents=True)
    # missing-file orphan
    pair = _pair(corpus, "working/stamp", "gggggggggggg", [])
    doc = sc.read(pair / "meta.yaml")
    doc["artifacts"]["transcript"] = {"path": "./transcript.md"}
    sc.write(pair / "meta.yaml", doc)
    tasks.run(tmp_path, "corpus", [str(corpus)])
    out = capsys.readouterr().out
    assert "ffffffffffff" in out and "ORPHAN: no sidecar" in out
    assert "gggggggggggg" in out and "ORPHAN: missing" in out


def test_torn_sidecar_is_reported_not_fatal(tmp_path, capsys):
    from shapes.corpus.commands import status
    corpus = _corpus(tmp_path)
    _pair(corpus, "corpus", "aaaaaaaaaaaa", [], status="complete")   # healthy doc
    torn = corpus / "corpus" / "bbbbbbbbbbbb"
    torn.mkdir(parents=True)
    (torn / "meta.yaml").write_text("doc_id: [unclosed")             # torn yaml
    status.run(tmp_path, "corpus", [str(corpus)])                    # must not raise
    out = capsys.readouterr().out
    assert "torn sidecar" in out
    assert "corpus" in out                                           # healthy listing intact
