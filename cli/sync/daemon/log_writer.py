import json
from pathlib import Path

from cli.sync.daemon.events import SyncEvent


class LogWriter:
    def __init__(self, log_path: Path, max_bytes: int = 10_000_000, max_generations: int = 7):
        self._log_path = log_path
        self._max_bytes = max_bytes
        self._max_generations = max_generations

    def write(self, event: SyncEvent) -> None:
        line = json.dumps(event.to_dict()) + "\n"
        with open(self._log_path, "a") as f:
            f.write(line)
        self._maybe_rotate()

    def _maybe_rotate(self) -> None:
        if not self._log_path.exists():
            return
        if self._log_path.stat().st_size < self._max_bytes:
            return
        # Shift existing generations up
        for i in range(self._max_generations, 0, -1):
            src = self._log_path.parent / f"{self._log_path.name}.{i}"
            if i == self._max_generations:
                # Delete the oldest
                if src.exists():
                    src.unlink()
            else:
                dst = self._log_path.parent / f"{self._log_path.name}.{i + 1}"
                if src.exists():
                    src.rename(dst)
        # Current log becomes .1
        self._log_path.rename(
            self._log_path.parent / f"{self._log_path.name}.1"
        )
