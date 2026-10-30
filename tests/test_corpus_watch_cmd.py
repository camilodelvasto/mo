import pytest
from shapes.corpus.commands import watch


def test_watch_requires_a_corpus(tmp_path, capsys):
    (tmp_path / "capabilities.yaml").write_text("capabilities: {}\n")
    with pytest.raises(SystemExit):
        watch.run(tmp_path, "corpus", [str(tmp_path / "nowhere")])


def test_watch_refuses_unbound_capability(tmp_path, capsys):
    (tmp_path / "capabilities.yaml").write_text("capabilities: {}\n")
    corpus = tmp_path / "c"
    (corpus / "dropbox" / "general").mkdir(parents=True)
    (corpus / "corpus.yaml").write_text("id: c\nflow: ./flow.yaml\n")
    (corpus / "flow.yaml").write_text(
        "id: t\nversion: 1\n"
        "entrypoints: [{id: general, area: dropbox/general}]\n"
        "pipeline: [{id: x, uses: local.never-bound}]\n")
    with pytest.raises(SystemExit):
        watch.run(tmp_path, "corpus", [str(corpus)])
    err = capsys.readouterr().err
    assert "local.never-bound" in err


def test_watch_rejects_unknown_flag(tmp_path, capsys):
    # no fallbacks: a typo like --restat must be loud, never swallowed
    (tmp_path / "capabilities.yaml").write_text("capabilities: {}\n")
    with pytest.raises(SystemExit):
        watch.run(tmp_path, "corpus", [str(tmp_path), "--restat"])
    assert "unknown flag" in capsys.readouterr().err
