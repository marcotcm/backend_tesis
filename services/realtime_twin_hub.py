"""
Hub WebSocket en memoria para sincronización sub-segundo del Gemelo Digital P&ID.

Mantiene las conexiones activas de Salas de Control SCADA y difunde eventos
instantáneos ante ingesta de telemetría (individual o lote IoT), cambios
operativos de activos, actualización topológica P&ID o consignas SCADA.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from fastapi import WebSocket

logger = logging.getLogger("rcm_backend.twin_hub")


class TwinConnectionManager:
    def __init__(self) -> None:
        self._connections: Dict[WebSocket, Optional[str]] = {}

    @property
    def active_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket, taxonomy_id: Optional[str] = None) -> None:
        await websocket.accept()
        self._connections[websocket] = taxonomy_id
        logger.debug("Cliente WebSocket conectado al Gemelo Digital (activos=%s)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.pop(websocket, None)
        logger.debug("Cliente WebSocket desconectado del Gemelo Digital (activos=%s)", len(self._connections))

    async def broadcast_event(
        self,
        event_type: str,
        data: Optional[dict] = None,
        taxonomy_id: Optional[str] = None,
    ) -> int:
        if not self._connections:
            return 0

        payload = json.dumps(
            {
                "event": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": data or {},
            },
            default=str,
        )

        sent = 0
        dead: list[WebSocket] = []
        for ws, client_tax in list(self._connections.items()):
            if taxonomy_id and client_tax and client_tax != taxonomy_id:
                continue
            try:
                await ws.send_text(payload)
                sent += 1
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

        return sent


twin_hub = TwinConnectionManager()
