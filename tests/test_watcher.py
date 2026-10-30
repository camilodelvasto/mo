import time
from pathlib import Path
from unittest.mock import patch, MagicMock

from shapes.sheets.src.watcher import (
    detect_inbox_files,
    process_one_file,
    InboxHandler,
    clean_staging,
    drain_inbox,
)


def test_detect_empty_inbox(sheet_dir):
    inbox = sheet_dir / "ingest" / "inbox"
    files = list(detect_inbox_files(inbox))
    assert files == []


def test_detect_new_files(sheet_dir):
    inbox = sheet_dir / "ingest" / "inbox"
    (inbox / "entry-001.txt").write_text("NEW\nsome content")
    (inbox / "entry-002.txt").write_text("UPDATE row_id=r123\nlog text")
    files = sorted(detect_inbox_files(inbox), key=lambda p: p.name)
    assert len(files) == 2
    assert files[0].name == "entry-001.txt"
    assert files[1].name == "entry-002.txt"


def test_detect_ignores_dotfiles(sheet_dir):
    inbox = sheet_dir / "ingest" / "inbox"
    (inbox / ".hidden").write_text("ignored")
    (inbox / "entry.txt").write_text("NEW\ncontent")
    files = list(detect_inbox_files(inbox))
    assert len(files) == 1
    assert files[0].name == "entry.txt"


def test_process_one_file(sheet_dir):
    inbox = sheet_dir / "ingest" / "inbox"
    (inbox / "entry.txt").write_text("NEW\ncontent")

    with patch("shapes.sheets.src.watcher.process_file") as mock_process:
        process_one_file(sheet_dir)

    mock_process.assert_called_once()
    assert mock_process.call_args[0][0].name == "entry.txt"


def test_process_one_file_timeout(sheet_dir):
    import pytest

    with pytest.raises(TimeoutError):
        process_one_file(sheet_dir, timeout=0.1)


def test_on_processed_callback(sheet_dir):
    inbox = sheet_dir / "ingest" / "inbox"
    (inbox / "entry.txt").write_text("NEW\ncontent")
    callback = MagicMock()

    with patch("shapes.sheets.src.watcher.process_file"):
        process_one_file(sheet_dir, on_processed=callback)

    callback.assert_called_once()


def test_inbox_handler_has_lock(sheet_dir):
    handler = InboxHandler(
        content_dir=sheet_dir,
        corpus_root=None,
        api_url="http://127.0.0.1:4200",
    )
    assert hasattr(handler, "lock")


def test_startup_cleans_staging(sheet_dir):
    staging = sheet_dir / "ingest" / "staging"
    staging.mkdir(exist_ok=True)
    (staging / "leftover.txt").write_text("partial write")

    clean_staging(sheet_dir)
    assert list(staging.iterdir()) == []


def test_startup_drains_existing_inbox(sheet_dir):
    inbox = sheet_dir / "ingest" / "inbox"
    (inbox / "existing.txt").write_text("NEW\npre-existing")

    with patch("shapes.sheets.src.watcher.process_file") as mock_process:
        drain_inbox(sheet_dir)

    mock_process.assert_called_once()
