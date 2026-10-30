import fnmatch
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from cli.sync.daemon.scheduler import FolderScheduler

IGNORED_PATTERNS = {
    ".DS_Store",
    "*.swp",
    "*~",
    ".#*",
    "state.sqlite",
    "__pycache__",
    ".rendered",
    ".git",
}


def _is_ignored(path: str) -> bool:
    parts = Path(path).parts
    for part in parts:
        for pattern in IGNORED_PATTERNS:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


class _FolderHandler(FileSystemEventHandler):
    def __init__(self, scheduler: FolderScheduler):
        super().__init__()
        self._scheduler = scheduler

    def on_any_event(self, event):
        if _is_ignored(event.src_path):
            return
        self._scheduler.poke()


class FolderWatcher:
    def __init__(self, folder: Path, scheduler: FolderScheduler):
        self._folder = folder
        self._handler = _FolderHandler(scheduler)
        self._observer = Observer()

    def start(self):
        self._observer.schedule(self._handler, str(self._folder), recursive=True)
        self._observer.start()

    def stop(self):
        self._observer.stop()
        self._observer.join(timeout=5)
