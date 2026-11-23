"""WebSocket-Hub: verteilt Änderungsereignisse an alle Geräte einer Firma."""
import asyncio
import logging
from typing import Optional

from fastapi import WebSocket

log = logging.getLogger("dienstplan.hub")


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[int, dict[WebSocket, int]] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    async def connect(self, ws: WebSocket, tenant_id: int, user_id: int) -> None:
        await ws.accept()
        self.rooms.setdefault(tenant_id, {})[ws] = user_id

    def disconnect(self, ws: WebSocket, tenant_id: int) -> None:
        self.rooms.get(tenant_id, {}).pop(ws, None)

    async def _broadcast(self, tenant_id: int, message: dict, user_ids: Optional[list[int]]) -> None:
        for ws, uid in list(self.rooms.get(tenant_id, {}).items()):
            if user_ids is not None and uid not in user_ids:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                self.rooms.get(tenant_id, {}).pop(ws, None)

    def notify(self, tenant_id: int, event: str, data: Optional[dict] = None,
               user_ids: Optional[list[int]] = None) -> None:
        """Thread-sicher: darf aus synchronen Endpunkten (Threadpool) aufgerufen werden."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        msg = {"event": event, "data": data or {}}
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(tenant_id, msg, user_ids), loop)
        except Exception:
            log.exception("WebSocket-Benachrichtigung fehlgeschlagen")


hub = Hub()
