"""
Servicio integral de notificaciones para Heimdall RCM.
Gestiona las conexiones WebSocket en tiempo real, integración con Expo Push Notifications,
y expone los métodos que serán llamados automáticamente por los otros módulos (Métricas, IA, OTs, Mantenimiento).
"""

import json
import httpx
from typing import List, Optional
from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from crud.notification import create_notification
from schemas.notification import NotificationCreate
from services import user_push_token as push_service
from models.user import User


# Manejador de WebSockets en tiempo real
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json.dumps(message, default=str))
            except Exception:
                pass  # Ignorar conexiones caídas


manager = ConnectionManager()


# Integración con Expo Push Notifications
async def send_expo_push_notifications(tokens: List[str], title: str, message: str, data: dict = None):
    if not tokens:
        return

    messages = [{
        "to": token,
        "title": title,
        "body": message,
        "sound": "default",
        "data": data or {}
    } for token in tokens if token]

    if not messages:
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(
                "https://exp.host/--/api/v2/push/send",
                json=messages,
                headers={
                    "Accept": "application/json",
                    "Accept-encoding": "gzip, deflate",
                    "Content-Type": "application/json"
                }
            )
        except Exception as e:
            print(f"[ERROR PUSH] Fallo enviando notificación Expo: {e}")


# ==============================================================================
# TRIGGERS AUTOMÁTICOS (Llamados desde equipment_metrics, ai_predictive, etc.)
# ==============================================================================

async def trigger_global_alert(db: AsyncSession, title: str, message: str, user_id: Optional[uuid.UUID] = None):
    """1. Se dispara sola si se sube una MÉTRICA MALA (Fuera de umbrales)"""
    notif_data = NotificationCreate(
        title=title,
        message=message,
        notification_type="alerta",
        user_id=user_id
    )
    db_notif = await create_notification(db, notif_data)
    await db.commit()

    payload_ws = {
        "id": str(getattr(db_notif, "id", uuid.uuid4())),
        "title": title,
        "message": message,
        "type": "alerta",
        "notification_type": "alerta",
        "is_read": False,
        "created_at": getattr(db_notif, "created_at", None)
    }

    await manager.broadcast({"event": "new_alert", "data": payload_ws})

    try:
        tokens_db = await push_service.list_all_tokens(db)
        tokens = [t.token for t in tokens_db]
        await send_expo_push_notifications(tokens, title, message, data=payload_ws)
    except Exception as e:
        print(f"[WARN PUSH] No se pudieron enviar push tokens en alerta global: {e}")

    return db_notif


async def notify_ai_analysis_ready(
    db: AsyncSession,
    title: str,
    message: str,
    user_id: Optional[uuid.UUID] = None
):
    """2. Se dispara sola cuando la IA termina de generar un ANÁLISIS o PLAN"""
    notif_data = NotificationCreate(
        title=title,
        message=message,
        notification_type="ia",
        user_id=user_id
    )
    db_notif = await create_notification(db, notif_data)
    await db.commit()

    payload_ws = {
        "id": str(getattr(db_notif, "id", uuid.uuid4())),
        "title": title,
        "message": message,
        "type": "ia",
        "notification_type": "ia",
        "user_id": str(user_id) if user_id else None,
        "is_read": False,
        "created_at": getattr(db_notif, "created_at", None)
    }

    # Emitir ambos eventos por WebSocket para que el frontend lo capture tanto en el listener general como en el de IA
    await manager.broadcast({"event": "ai_analysis_ready", "data": payload_ws})
    await manager.broadcast({"event": "new_alert", "data": payload_ws})

    try:
        if user_id:
            tokens_db = await push_service.list_user_tokens(db, user_id=user_id)
            if not tokens_db:
                tokens_db = await push_service.list_all_tokens(db)
        else:
            tokens_db = await push_service.list_all_tokens(db)

        tokens = [t.token for t in tokens_db]
        await send_expo_push_notifications(tokens, title, message, data=payload_ws)
    except Exception as e:
        print(f"[WARN PUSH] No se pudieron enviar push tokens en notificación IA: {e}")

    return db_notif


async def notify_work_order_assignment(db: AsyncSession, user_id: uuid.UUID, title: str, message: str):
    """3. Se dispara sola cuando se asigna una ORDEN DE TRABAJO a un técnico"""
    notif_data = NotificationCreate(
        title=title,
        message=message,
        notification_type="orden_trabajo",
        user_id=user_id
    )
    db_notif = await create_notification(db, notif_data)
    await db.commit()

    payload_ws = {
        "id": str(getattr(db_notif, "id", uuid.uuid4())),
        "user_id": str(user_id),
        "title": title,
        "message": message,
        "type": "orden_trabajo",
        "notification_type": "orden_trabajo",
        "is_read": False,
        "created_at": getattr(db_notif, "created_at", None)
    }

    await manager.broadcast({"event": "work_order_assigned", "data": payload_ws})
    await manager.broadcast({"event": "new_alert", "data": payload_ws})

    try:
        tokens_db = await push_service.list_user_tokens(db, user_id=user_id)
        tokens = [t.token for t in tokens_db]
        await send_expo_push_notifications(tokens, title, message, data=payload_ws)
    except Exception as e:
        print(f"[WARN PUSH] No se pudieron enviar push tokens en OT: {e}")

    return db_notif


async def notify_new_maintenance(db: AsyncSession, title: str, message: str, user_id: Optional[uuid.UUID] = None):
    """4. Se dispara sola cuando se inicia un NUEVO MANTENIMIENTO"""
    notif_data = NotificationCreate(
        title=title,
        message=message,
        notification_type="sistema",
        user_id=user_id
    )
    db_notif = await create_notification(db, notif_data)
    await db.commit()

    payload_ws = {
        "id": str(getattr(db_notif, "id", uuid.uuid4())),
        "title": title,
        "message": message,
        "type": "sistema",
        "notification_type": "sistema",
        "is_read": False,
        "created_at": getattr(db_notif, "created_at", None)
    }

    await manager.broadcast({"event": "new_maintenance", "data": payload_ws})
    await manager.broadcast({"event": "new_alert", "data": payload_ws})

    try:
        tokens_db = await push_service.list_all_tokens(db)
        tokens = [t.token for t in tokens_db]
        await send_expo_push_notifications(tokens, title, message, data=payload_ws)
    except Exception as e:
        print(f"[WARN PUSH] No se pudieron enviar push tokens en mantenimiento: {e}")

    return db_notif