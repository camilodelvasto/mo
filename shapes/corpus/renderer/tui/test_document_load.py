# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Regression: DocumentScreen.on_mount must not write a torn-down DOM.

on_mount loads over the wire (doc/chunks/log + transcript). Those awaits yield to
the event loop; an `esc` during that window pops the screen. The load runs in a
worker so unmount cancels it — the contract this test pins is "pop during load
does not crash", not any specific rendered value. Before the fix the load ran
inline in on_mount, resumed after the pop, and raised NoMatches on #header-line."""
import asyncio

import pytest
from textual.app import App

from shapes.corpus.renderer.tui.document import DocumentScreen


class GatedClient:
    """A client whose reads block on a gate until the test releases them, so the
    screen can be popped while the very first load await is still pending."""

    def __init__(self):
        self.gate = asyncio.Event()

    async def doc(self, doc_id):
        await self.gate.wait()
        return {"status": "ready", "flow": {"id": "f", "version": 1}, "fields": {}}

    async def chunks(self, doc_id):
        await self.gate.wait()
        return {"chunks": []}

    async def log(self, doc_id):
        await self.gate.wait()
        return {"entries": []}

    async def artifact(self, doc_id, name):
        return b""


class Host(App):
    def __init__(self, client):
        super().__init__()
        self._client = client

    def push_doc(self):
        self.push_screen(DocumentScreen("deadbeef", self._client, bindings=[]))


@pytest.mark.asyncio
async def test_pop_during_load_does_not_crash():
    client = GatedClient()
    app = Host(client)
    async with app.run_test() as pilot:
        app.push_doc()
        await pilot.pause()                 # worker starts, blocks on the first read
        app.pop_screen()                    # esc before any payload arrives
        await pilot.pause()
        client.gate.set()                   # reads unblock; a live load would now
        await pilot.pause()                 # resume and query the popped DOM
        # The app is still running — the cancelled load never touched the dead DOM.
        assert app.is_running


@pytest.mark.asyncio
async def test_full_load_renders_header():
    """The happy path still loads: header reflects the doc once reads complete."""
    client = GatedClient()
    client.gate.set()                       # no blocking — load runs straight through
    app = Host(client)
    async with app.run_test() as pilot:
        app.push_doc()
        screen = app.screen
        for _ in range(50):
            await pilot.pause()
            if screen._ready:
                break
        assert screen._ready
        header = screen.query_one("#header-line")
        assert "deadbeef"[:6] in header.renderable
