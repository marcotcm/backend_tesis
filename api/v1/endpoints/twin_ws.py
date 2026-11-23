"""
Endpoint WebSocket para transmisión en tiempo real hacia la Sala de Control SCADA.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from services.realtime_twin_hub import twin_hub

logger = logging.getLogger("rcm_backend.twin_ws")

router = APIRouter()


def _is_valid_ws_token(token: Optional[str]) -> bool:
    if not token:
        return False
    if token.startswith("demo-"):
        return True
    try:
        payload = jwt.decode(
            token,
            options={"verify_signature": False},
            algorithms=["ES256", "HS256"],
            audience="authenticated",
        )
        return bool(payload.get("sub"))
    except Exception:
        return False


@router.websocket("/ws")
async def digital_twin_realtime_stream(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    taxonomy_id: Optional[str] = Query(None),
):
    if not _is_valid_ws_token(token):
        await websocket.close(code=1008)
        return

    await twin_hub.connect(websocket, taxonomy_id=taxonomy_id)
    try:
        await websocket.send_text(
            json.dumps(
                {
                    "event": "connected",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {"mode": "realtime_ws", "clients": twin_hub.active_count},
                }
            )
        )

        while True:
            try:
                raw_msg = await asyncio.wait_for(websocket.receive_text(), timeout=25.0)
                if raw_msg.strip().lower() == "ping" or '"ping"' in raw_msg:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "event": "pong",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "data": {},
                            }
                        )
                    )
            except asyncio.TimeoutError:
                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "heartbeat",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "data": {"clients": twin_hub.active_count},
                        }
                    )
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Canal WebSocket cerrado: %s", exc)
    finally:
        twin_hub.disconnect(websocket)
