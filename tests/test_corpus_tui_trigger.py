# tests/test_corpus_tui_trigger.py
from shapes.corpus.renderer.tui.trigger import TimerTrigger


class _FakeScreen:
    def __init__(self):
        self.interval = None
        self.refetched = []

    def set_interval(self, seconds, callback):
        self.interval = (seconds, callback)

    def refetch(self, target):
        self.refetched.append(target)


def test_timer_trigger_wires_an_interval_that_refetches_all():
    screen = _FakeScreen()
    TimerTrigger(interval=1.5).start(screen)
    assert screen.interval[0] == 1.5
    screen.interval[1]()                       # fire the wired callback
    assert screen.refetched == ["all"]         # bounded page + counts, not a row
