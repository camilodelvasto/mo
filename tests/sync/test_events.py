import asyncio
import pytest
from cli.sync.daemon.events import SyncEvent, EventBroadcaster


def test_event_has_type_and_folder():
    ev = SyncEvent(type="push_ok", folder="content")
    assert ev.type == "push_ok"
    assert ev.folder == "content"
    assert ev.ts  # non-empty ISO timestamp


def test_event_to_dict():
    ev = SyncEvent(type="push_ok", folder="content", sha="abc123", files=3)
    d = ev.to_dict()
    assert d["type"] == "push_ok"
    assert d["folder"] == "content"
    assert d["ts"]
    assert d["sha"] == "abc123"
    assert d["files"] == 3


@pytest.mark.asyncio
async def test_subscribe_receives_events():
    bc = EventBroadcaster()
    received = []

    async def collect():
        async for ev in bc.subscribe():
            received.append(ev)
            if len(received) == 2:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)
    await bc.emit(SyncEvent(type="a", folder="f1"))
    await bc.emit(SyncEvent(type="b", folder="f2"))
    await asyncio.wait_for(task, timeout=1.0)
    assert len(received) == 2
    assert received[0].type == "a"
    assert received[1].type == "b"


@pytest.mark.asyncio
async def test_folder_filter():
    bc = EventBroadcaster()
    received = []

    async def collect():
        async for ev in bc.subscribe(folder="infra"):
            received.append(ev)
            if len(received) == 1:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)
    await bc.emit(SyncEvent(type="a", folder="content"))
    await bc.emit(SyncEvent(type="b", folder="infra"))
    await asyncio.wait_for(task, timeout=1.0)
    assert len(received) == 1
    assert received[0].folder == "infra"
