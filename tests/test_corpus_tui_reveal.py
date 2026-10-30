# tests/test_corpus_tui_reveal.py
from shapes.corpus.renderer.tui import reveal as revealmod


def _capture():
    calls = []
    return calls, (lambda cmd, **kw: calls.append((cmd, kw)))


def test_macos_reveals_in_finder():
    calls, runner = _capture()
    cmd = revealmod.reveal("/c/505c/original.pdf", runner=runner, platform="darwin")
    assert cmd == ["open", "-R", "/c/505c/original.pdf"]
    assert calls[0][0] == cmd


def test_windows_selects_in_explorer():
    calls, runner = _capture()
    cmd = revealmod.reveal("C:\\c\\original.pdf", runner=runner, platform="win32")
    assert cmd == ["explorer", "/select,C:\\c\\original.pdf"]


def test_linux_opens_the_containing_folder():
    calls, runner = _capture()
    cmd = revealmod.reveal("/c/505c/original.pdf", runner=runner, platform="linux")
    assert cmd == ["xdg-open", "/c/505c"]
