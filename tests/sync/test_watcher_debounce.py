import asyncio

import pytest


@pytest.mark.asyncio
async def test_debounce_fires_after_quiet():
    from cli.sync.daemon.scheduler import FolderScheduler

    fired = []

    async def on_sync(folder: str):
        fired.append(folder)

    s = FolderScheduler("content", debounce_seconds=0.1, max_debounce_seconds=5.0, on_sync=on_sync, loop=asyncio.get_running_loop())
    s.poke()
    await asyncio.sleep(0.25)
    assert fired == ["content"]


@pytest.mark.asyncio
async def test_debounce_resets_on_repeated_pokes():
    from cli.sync.daemon.scheduler import FolderScheduler

    fired = []

    async def on_sync(folder: str):
        fired.append(folder)

    s = FolderScheduler("docs", debounce_seconds=0.15, max_debounce_seconds=5.0, on_sync=on_sync, loop=asyncio.get_running_loop())
    for _ in range(5):
        s.poke()
        await asyncio.sleep(0.05)
    # After last poke we need to wait for debounce to elapse
    await asyncio.sleep(0.25)
    assert fired == ["docs"]


@pytest.mark.asyncio
async def test_max_debounce_forces_sync():
    from cli.sync.daemon.scheduler import FolderScheduler

    fired = []

    async def on_sync(folder: str):
        fired.append(folder)

    # max_debounce shorter than debounce — forces fire before debounce elapses
    s = FolderScheduler("infra", debounce_seconds=2.0, max_debounce_seconds=0.15, on_sync=on_sync, loop=asyncio.get_running_loop())
    s.poke()
    await asyncio.sleep(0.05)
    assert fired == []  # not yet
    await asyncio.sleep(0.2)
    assert fired == ["infra"]


@pytest.mark.asyncio
async def test_cancel_stops_pending():
    from cli.sync.daemon.scheduler import FolderScheduler

    fired = []

    async def on_sync(folder: str):
        fired.append(folder)

    s = FolderScheduler("content", debounce_seconds=0.1, max_debounce_seconds=5.0, on_sync=on_sync, loop=asyncio.get_running_loop())
    s.poke()
    s.cancel()
    await asyncio.sleep(0.25)
    assert fired == []
