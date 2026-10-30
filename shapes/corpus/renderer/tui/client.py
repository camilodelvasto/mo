# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The renderer's service client. The TUI talks to the read service and nothing
else; embed mode runs the service in-process over an ASGITransport (no socket),
so 'embed now / attach to serve later / web eventually' is a different
constructor, never a different screen."""
from pathlib import Path

import httpx
from httpx import ASGITransport

from shapes.corpus.service.app import create_app


class ServiceClient:
    """Async wrappers over the read endpoints the catalogue uses."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def status(self) -> dict:
        return (await self._get("/status"))

    async def counts(self) -> dict:
        return (await self._get("/catalogue/counts"))

    async def facets(self) -> dict:
        return (await self._get("/facets"))

    async def fields(self) -> dict:
        return (await self._get("/fields"))

    async def catalogue(self, lens: str = "all", where: str = "",
                        field: str | None = None, value: str | None = None,
                        cursor: int = 0, limit: int = 100) -> dict:
        params = {"lens": lens, "cursor": cursor, "limit": limit}
        if where:
            params["where"] = where
        if field is not None and value is not None:
            params["field"] = field
            params["value"] = value
        return (await self._get("/catalogue", params=params))

    async def row(self, doc_id: str) -> dict | None:
        r = await self._http.get(f"/catalogue/{doc_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def doc(self, doc_id: str) -> dict:
        return await self._get(f"/doc/{doc_id}")

    async def custody(self, doc_id: str) -> dict:
        return await self._get(f"/doc/{doc_id}/custody")

    async def chunks(self, doc_id: str) -> dict:
        return await self._get(f"/doc/{doc_id}/chunks")

    async def log(self, doc_id: str) -> dict:
        return await self._get(f"/doc/{doc_id}/log")

    async def doc_path(self, doc_id: str, name: str = "original") -> str | None:
        """The artifact's absolute on-disk path (for an OS reveal), or None when
        the bytes are gone (custody-only). Raises on other non-2xx."""
        r = await self._http.get(f"/doc/{doc_id}/path", params={"artifact": name})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()["path"]

    async def artifact(self, doc_id: str, name: str) -> bytes:
        """The artifact's raw bytes — NOT decoded or normalized. The caller
        decodes UTF-8 for the transcript, matching the chunker."""
        r = await self._http.get(f"/doc/{doc_id}/artifacts/{name}")
        r.raise_for_status()
        return r.content

    async def search(self, q: str) -> list:
        return (await self._get("/search", params={"q": q}))["hits"]

    async def post_assert(self, body: dict) -> dict:
        r = await self._http.post("/assert", json=body)
        r.raise_for_status()
        return r.json()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        r = await self._http.get(path, params=params or {})
        r.raise_for_status()
        return r.json()

    async def events(self):
        """Yield {doc_id, change} dicts from the /events SSE stream."""
        import json
        async with self._http.stream("GET", "/events", timeout=None) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    yield json.loads(line[len("data:"):].strip())

    async def aclose(self) -> None:
        await self._http.aclose()


def embed_client(corpus_dir: Path, machine_root: Path | None = None):
    """Build a ServiceClient over an in-process ASGITransport. Returns
    (client, app) — the app is kept so a trigger can drive its poller."""
    app = create_app(corpus_dir, machine_root=machine_root)
    http = httpx.AsyncClient(transport=ASGITransport(app=app),
                            base_url="http://embed")
    return ServiceClient(http), app
