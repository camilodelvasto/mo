import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator


@dataclass
class SyncEvent:
    type: str
    folder: str
    ts: str = ""
    _extra: dict = field(default_factory=dict, repr=False)

    def __init__(self, *, type: str, folder: str, ts: str = "", **kwargs):
        self.type = type
        self.folder = folder
        self.ts = ts or datetime.now(timezone.utc).isoformat()
        self._extra = kwargs

    def to_dict(self) -> dict:
        return {"type": self.type, "folder": self.folder, "ts": self.ts, **self._extra}


class EventBroadcaster:
    def __init__(self):
        self._subscribers: list[tuple[asyncio.Queue, str | None]] = []

    async def emit(self, event: SyncEvent) -> None:
        for queue, folder_filter in self._subscribers:
            if folder_filter is None or event.folder == folder_filter:
                await queue.put(event)

    async def subscribe(self, folder: str | None = None) -> AsyncIterator[SyncEvent]:
        queue: asyncio.Queue[SyncEvent] = asyncio.Queue()
        entry = (queue, folder)
        self._subscribers.append(entry)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscribers.remove(entry)
