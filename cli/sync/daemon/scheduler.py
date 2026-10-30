import asyncio
import time
from typing import Callable, Coroutine


class FolderScheduler:
    def __init__(
        self,
        folder_name: str,
        debounce_seconds: float,
        max_debounce_seconds: float,
        on_sync: Callable[[str], Coroutine],
        loop: asyncio.AbstractEventLoop,
    ):
        self._folder_name = folder_name
        self._debounce = debounce_seconds
        self._max_debounce = max_debounce_seconds
        self._on_sync = on_sync
        self._loop = loop
        self._timer: asyncio.Task | None = None
        self._first_poke_time: float | None = None
        self._cancelled = False

    def poke(self):
        """Thread-safe: can be called from watchdog's thread."""
        self._cancelled = False
        self._loop.call_soon_threadsafe(self._poke_on_loop)

    def _poke_on_loop(self):
        """Runs on the asyncio event loop thread."""
        if self._cancelled:
            return
        now = time.monotonic()

        if self._first_poke_time is None:
            self._first_poke_time = now

        elapsed = now - self._first_poke_time

        if elapsed >= self._max_debounce:
            self._fire_now()
            return

        remaining_max = self._max_debounce - elapsed
        delay = min(self._debounce, remaining_max)

        if self._timer is not None:
            self._timer.cancel()

        self._timer = self._loop.create_task(self._wait_and_fire(delay))

    def cancel(self):
        self._cancelled = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._first_poke_time = None

    async def _wait_and_fire(self, delay: float):
        await asyncio.sleep(delay)
        self._first_poke_time = None
        self._timer = None
        await self._on_sync(self._folder_name)

    def _fire_now(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._first_poke_time = None
        self._loop.create_task(self._on_sync(self._folder_name))
