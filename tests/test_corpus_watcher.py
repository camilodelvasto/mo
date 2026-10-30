from shapes.corpus.engine.watcher import Watcher


ENTRYPOINTS = [
    {"id": "general", "area": "dropbox/general", "fields": {"visibility": "general"}},
    {"id": "private", "area": "dropbox/private", "fields": {"visibility": "private"}},
]


def _corpus(tmp_path):
    for sub in ("dropbox/general", "dropbox/private", "inbox"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "flow.yaml").write_text("id: t\nversion: 1\n")
    return tmp_path


def test_drop_settles_after_two_stable_ticks(tmp_path):
    corpus = _corpus(tmp_path)
    w = Watcher(corpus, ENTRYPOINTS)
    f = corpus / "dropbox" / "general" / "a.txt"
    f.write_text("hello")
    assert w.tick() == []                      # first sighting: record size
    events = w.tick()                          # size unchanged: settled
    assert [(e.kind, e.path.name, e.entrypoint["id"]) for e in events] == \
        [("dropped", "a.txt", "general")]
    assert w.tick() == []                      # consumed — fires once


def test_growing_file_does_not_settle(tmp_path):
    corpus = _corpus(tmp_path)
    w = Watcher(corpus, ENTRYPOINTS)
    f = corpus / "dropbox" / "private" / "big.bin"
    f.write_bytes(b"x" * 10)
    w.tick()
    f.write_bytes(b"x" * 20)                   # still being written
    assert w.tick() == []
    events = w.tick()                          # now stable
    assert len(events) == 1 and events[0].entrypoint["id"] == "private"


def test_hidden_and_gitkeep_ignored(tmp_path):
    corpus = _corpus(tmp_path)
    (corpus / "dropbox" / "general" / ".gitkeep").write_text("")
    (corpus / "dropbox" / "general" / ".DS_Store").write_text("x")
    w = Watcher(corpus, ENTRYPOINTS)
    w.tick()
    assert w.tick() == []


def test_assert_file_fires_immediately(tmp_path):
    corpus = _corpus(tmp_path)
    w = Watcher(corpus, ENTRYPOINTS)
    w.tick()
    (corpus / "inbox" / "01J8X-aaaaaaaaaaaa.assert.yaml").write_text("doc_id: aaaaaaaaaaaa\n")
    events = w.tick()
    assert [e.kind for e in events] == ["assert"]
    assert w.tick() == []                      # fires once per file


def test_flow_edit_fires_once(tmp_path):
    corpus = _corpus(tmp_path)
    w = Watcher(corpus, ENTRYPOINTS)
    w.tick()
    (corpus / "flow.yaml").write_text("id: t\nversion: 2\n")
    events = w.tick()
    assert [e.kind for e in events] == ["flow-changed"]
    assert w.tick() == []


def test_vanished_drop_is_forgotten_and_new_same_path_settles_fresh(tmp_path):
    corpus = _corpus(tmp_path)
    w = Watcher(corpus, ENTRYPOINTS)
    f = corpus / "dropbox" / "general" / "a.txt"
    f.write_text("12345")
    w.tick()                                   # recorded
    f.unlink()                                 # vanished before settling
    w.tick()                                   # pruned
    f.write_text("54321")                      # same path, same size
    assert w.tick() == []                      # fresh file: recorded, NOT settled
    assert len(w.tick()) == 1                  # settles on its own second tick


def test_reused_assert_path_fires_again_after_consumption(tmp_path):
    corpus = _corpus(tmp_path)
    w = Watcher(corpus, ENTRYPOINTS)
    w.tick()
    f = corpus / "inbox" / "01X-aaaaaaaaaaaa.assert.yaml"
    f.write_text("doc_id: aaaaaaaaaaaa\n")
    assert [e.kind for e in w.tick()] == ["assert"]
    f.unlink()                                 # engine consumed it
    w.tick()                                   # pruned
    f.write_text("doc_id: aaaaaaaaaaaa\n")     # human re-drops same filename
    assert [e.kind for e in w.tick()] == ["assert"]


def test_entrypoint_pattern_filters_files(tmp_path):
    corpus = _corpus(tmp_path)
    eps = [{"id": "general", "area": "dropbox/general",
            "pattern": "*.txt", "fields": {}}]
    w = Watcher(corpus, eps)
    (corpus / "dropbox" / "general" / "a.txt").write_text("x")
    (corpus / "dropbox" / "general" / "b.pdf").write_text("x")
    w.tick()
    events = w.tick()
    assert [e.path.name for e in events] == ["a.txt"]   # b.pdf never settles in
