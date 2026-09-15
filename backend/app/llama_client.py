"""The one place that talks HTTP to a running llama-server.

Everything the panel wants to know about the inference server itself
(is it up, is it loading, is it generating) goes through this client, so
the endpoint quirks - wildcard bind addresses, /slots being optional,
/health returning 503 while the model loads - are handled once.
"""

from __future__ import annotations

from typing import Optional

import httpx


def _query_host(host: str) -> str:
    # A server bound to a wildcard address is reached via loopback.
    return "127.0.0.1" if host in ("0.0.0.0", "::") else host


class LlamaClient:
    def __init__(self, timeout: float = 2.0, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def is_healthy(self, host: str, port: int) -> bool | None:
        """llama-server's /health: 200 once the model is loaded and it can
        serve requests, 503 while it's still loading. None when the server
        isn't reachable at all (not up yet, wrong port, crashed)."""
        try:
            resp = await self._http.get(f"http://{_query_host(host)}:{port}/health")
        except httpx.HTTPError:
            return None
        if resp.status_code == 200:
            return True
        if resp.status_code == 503:
            return False
        return None

    async def is_busy(self, host: str, port: int) -> bool | None:
        """Whether any slot is mid-generation, according to llama-server's
        own /slots bookkeeping. Works no matter who sent the request
        (Hermes, the llama.cpp webui, curl, ...) - callers of this panel
        never need to signal anything.

        Returns None if the check is inconclusive (server unreachable, or
        started with --no-slots) rather than guessing true/false.
        """
        try:
            resp = await self._http.get(f"http://{_query_host(host)}:{port}/slots")
            resp.raise_for_status()
            slots = resp.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(slots, list):
            return None
        return any(slot.get("is_processing") for slot in slots)
