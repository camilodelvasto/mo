import logging
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from shapes.sheets.src.processor import process_file

log = logging.getLogger("sheets.watcher")


def detect_inbox_files(inbox: Path) -> list[Path]:
    """Return non-dotfiles in the inbox directory, sorted by modification time."""
    if not inbox.exists():
        return []
    return sorted(
        (f for f in inbox.iterdir() if f.is_file() and not f.name.startswith(".")),
        key=lambda p: p.stat().st_mtime,
    )


def clean_staging(content_dir: Path) -> None:
    """Delete leftover files in staging/ from previous crashes."""
    staging = Path(content_dir) / "ingest" / "staging"
    if staging.exists():
        for f in staging.iterdir():
            if f.is_file():
                f.unlink()
                log.info("Cleaned stale staging file: %s", f.name)


def drain_inbox(
    content_dir: Path,
    corpus_root: Path | None = None,
    api_url: str = "http://127.0.0.1:4200",
    on_processed: Callable | None = None,
) -> None:
    """Process any files already in inbox/ on startup."""
    content_dir = Path(content_dir)
    inbox = content_dir / "ingest" / "inbox"
    for file_path in detect_inbox_files(inbox):
        try:
            process_file(file_path, content_dir, corpus_root=corpus_root, api_url=api_url)
            if on_processed:
                on_processed()
        except Exception as e:
            log.error("Failed to process %s: %s", file_path.name, e)


def process_one_file(
    content_dir: Path,
    corpus_root: Path | None = None,
    api_url: str = "http://127.0.0.1:4200",
    on_processed: Callable | None = None,
    timeout: float = 2.0,
) -> None:
    """Process a single inbox file synchronously. For tests."""
    content_dir = Path(content_dir)
    inbox = content_dir / "ingest" / "inbox"
    deadline = time.time() + timeout
    while time.time() < deadline:
        files = detect_inbox_files(inbox)
        if files:
            process_file(files[0], content_dir, corpus_root=corpus_root, api_url=api_url)
            if on_processed:
                on_processed()
            return
        time.sleep(0.01)
    raise TimeoutError("No file appeared in inbox")


class InboxHandler(FileSystemEventHandler):
    """Watchdog handler that processes inbox files serially."""

    def __init__(
        self,
        content_dir: Path,
        corpus_root: Path | None = None,
        api_url: str = "http://127.0.0.1:4200",
        on_processed: Callable | None = None,
    ):
        self.content_dir = Path(content_dir)
        self.corpus_root = corpus_root
        self.api_url = api_url
        self.on_processed = on_processed
        self.lock = threading.Lock()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.name.startswith("."):
            return
        with self.lock:
            try:
                process_file(
                    path, self.content_dir,
                    corpus_root=self.corpus_root, api_url=self.api_url,
                )
                if self.on_processed:
                    self.on_processed()
            except Exception as e:
                log.error("Failed to process %s: %s", path.name, e)


def watch_inbox(
    content_dir: Path,
    corpus_root: Path | None = None,
    api_url: str = "http://127.0.0.1:4200",
    on_processed: Callable | None = None,
) -> None:
    """Watch inbox/ for new files using filesystem events."""
    content_dir = Path(content_dir)
    inbox = content_dir / "ingest" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    clean_staging(content_dir)
    drain_inbox(content_dir, corpus_root=corpus_root, api_url=api_url, on_processed=on_processed)

    handler = InboxHandler(
        content_dir=content_dir,
        corpus_root=corpus_root,
        api_url=api_url,
        on_processed=on_processed,
    )
    observer = Observer()
    observer.schedule(handler, str(inbox), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
