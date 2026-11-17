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


async def _resolver_user_id_por_defecto(db: AsyncSession, user_id: Optional[uuid.UUID] = None) -> Optional[uuid.UUID]:
    """Si user_id es None, obtiene el primer usuario activo/admin para asegurar que la notificación se asocie en BD."""
    if user_id:
        return user_id
    try:
        res = await db.execute(select(User.id).where(User.is_active == True).limit(1))
        return res.scalars().first()
    except Exception:
        return None


# Integración con Expo Push Notifications
async def send_expo_push_notifications(
    tokens: List[str],
    title: str,
    message: str,
    data: dict = None,
    channel_id: str = "default",
    db: Optional[AsyncSession] = None,
):
    valid_tokens = list({
        t.strip()
        for t in tokens
        if t
        and isinstance(t, str)
        and (t.strip().startswith("ExponentPushToken[") or t.strip().startswith("ExpoPushToken["))
    })
    if not valid_tokens:
        print(f"[INFO PUSH] No hay tokens Expo válidos en user_push_tokens para enviar: '{title}'")
        return

    invalid_tokens: List[str] = []
    chunk_size = 100

    async with httpx.AsyncClient(timeout=10.0) as client:
        for i in range(0, len(valid_tokens), chunk_size):
            batch_tokens = valid_tokens[i : i + chunk_size]
            messages = [
                {
                    "to": token,
                    "title": title,
                    "body": message,
                    "sound": "default",
                    "priority": "high",
                    "channelId": channel_id,
                    "data": data or {},
                }
                for token in batch_tokens
            ]

            try:
                res = await client.post(
                    "https://exp.host/--/api/v2/push/send",
                    json=messages,
                    headers={
                        "Accept": "application/json",
                        "Accept-encoding": "gzip, deflate",
                        "Content-Type": "application/json",
                    },
                )
                print(f"[EXPO PUSH] Lote ({len(batch_tokens)} disp.) | Canal: {channel_id} | Status: {res.status_code}")

                try:
                    resp_json = res.json()
                    tickets = resp_json.get("data", []) if isinstance(resp_json, dict) else []
                    for token, ticket in zip(batch_tokens, tickets):
                        if isinstance(ticket, dict) and ticket.get("status") == "error":
                            err_code = (ticket.get("details") or {}).get("error", "UnknownError")
                            err_msg = ticket.get("message", "")
                            print(f"[ERROR EXPO TICKET] token={token[:28]}... error={err_code} msg={err_msg}")
                            if err_code == "DeviceNotRegistered":
                                invalid_tokens.append(token)
                except Exception as parse_err:
                    print(f"[WARN PUSH] No se pudo parsear respuesta de Expo: {parse_err}")
            except Exception as e:
                print(f"[ERROR PUSH] Fallo enviando notificación Expo: {e}")

    if invalid_tokens and db is not None:
        try:
            await push_service.deactivate_tokens_by_value(db, invalid_tokens)
            print(f"[INFO PUSH] Desactivados {len(invalid_tokens)} token(s) DeviceNotRegistered.")
        except Exception as cleanup_err:
            print(f"[WARN PUSH] Error limpiando tokens inválidos: {cleanup_err}")


# ==============================================================================
# TRIGGERS AUTOMÁTICOS (Llamados desde equipment_metrics, ai_predictive, etc.)
# ==============================================================================

async def trigger_global_alert(db: AsyncSession, title: str, message: str, user_id: Optional[uuid.UUID] = None):
    """1. Se dispara sola si se sube una MÉTRICA MALA (Fuera de umbrales)"""
    target_uid = await _resolver_user_id_por_defecto(db, user_id)
    notif_data = NotificationCreate(title=title, message=message, notification_type="alerta", user_id=target_uid)
    db_notif = await create_notification(db, notif_data)
    await db.commit()

    ws_payload = {
        "id": str(db_notif.id),
        "user_id": str(target_uid) if target_uid else None,
        "title": title,
        "message": message,
        "type": "alerta",
        "notification_type": "alerta",
        "is_read": False,
        "created_at": str(getattr(db_notif, "created_at", ""))
    }

    await manager.broadcast({"event": "new_alert", "data": ws_payload})

    try:
        tokens_db = await push_service.list_all_tokens(db)
        tokens = [t.token for t in tokens_db]
        await send_expo_push_notifications(
            tokens,
            title,
            message,
            data=ws_payload,
            channel_id="rcm_critical_alerts",
            db=db,
        )
    except Exception as e:
        print(f"[ERROR PUSH ALERTA] {e}")

    return db_notif


async def notify_ai_analysis_ready(db: AsyncSession, title: str, message: str, user_id: Optional[uuid.UUID] = None):
    """2. Se dispara sola cuando la IA termina de generar un ANÁLISIS o PLAN"""
    target_uid = await _resolver_user_id_por_defecto(db, user_id)
    notif_data = NotificationCreate(title=title, message=message, notification_type="ia", user_id=target_uid)
    db_notif = await create_notification(db, notif_data)
    await db.commit()

    ws_payload = {
        "id": str(db_notif.id),
        "user_id": str(target_uid) if target_uid else None,
        "title": title,
        "message": message,
        "type": "ia",
        "notification_type": "ia",
        "is_read": False,
        "created_at": str(getattr(db_notif, "created_at", ""))
    }

    # Emitir ambos eventos por WebSocket para que cualquier listener del frontend web lo muestre al instante
    await manager.broadcast({"event": "ai_analysis_ready", "data": ws_payload})
    await manager.broadcast({"event": "new_alert", "data": ws_payload})

    try:
        tokens_db = await push_service.list_all_tokens(db)
        tokens = [t.token for t in tokens_db]
        await send_expo_push_notifications(tokens, title, message, data=ws_payload, channel_id="default", db=db)
    except Exception as e:
        print(f"[ERROR PUSH IA] {e}")

    return db_notif


async def notify_work_order_assignment(db: AsyncSession, user_id: uuid.UUID, title: str, message: str):
    """3. Se dispara sola cuando se asigna una ORDEN DE TRABAJO a un técnico"""
    notif_data = NotificationCreate(title=title, message=message, notification_type="orden_trabajo", user_id=user_id)
    db_notif = await create_notification(db, notif_data)
    await db.commit()

    ws_payload = {
        "id": str(db_notif.id),
        "user_id": str(user_id),
        "title": title,
        "message": message,
        "type": "orden_trabajo",
        "notification_type": "orden_trabajo",
        "is_read": False,
        "created_at": str(getattr(db_notif, "created_at", ""))
    }

    await manager.broadcast({"event": "work_order_assigned", "data": ws_payload})
    await manager.broadcast({"event": "new_alert", "data": ws_payload})

    try:
        tokens_db = await push_service.list_user_tokens(db, user_id=user_id)
        if not tokens_db:
            tokens_db = await push_service.list_all_tokens(db)
        tokens = [t.token for t in tokens_db]
        await send_expo_push_notifications(tokens, title, message, data=ws_payload, channel_id="default", db=db)
    except Exception as e:
        print(f"[ERROR PUSH OT] {e}")

    return db_notif


async def notify_new_maintenance(db: AsyncSession, title: str, message: str, user_id: Optional[uuid.UUID] = None):
    """4. Se dispara sola cuando se inicia un NUEVO MANTENIMIENTO"""
    target_uid = await _resolver_user_id_por_defecto(db, user_id)
    notif_data = NotificationCreate(title=title, message=message, notification_type="sistema", user_id=target_uid)
    db_notif = await create_notification(db, notif_data)
    await db.commit()

    ws_payload = {
        "id": str(db_notif.id),
        "user_id": str(target_uid) if target_uid else None,
        "title": title,
        "message": message,
        "type": "sistema",
        "notification_type": "sistema",
        "is_read": False,
        "created_at": str(getattr(db_notif, "created_at", ""))
    }

    await manager.broadcast({"event": "new_maintenance", "data": ws_payload})
    await manager.broadcast({"event": "new_alert", "data": ws_payload})

    try:
        tokens_db = await push_service.list_all_tokens(db)
        tokens = [t.token for t in tokens_db]
        await send_expo_push_notifications(tokens, title, message, data=ws_payload, channel_id="default", db=db)
    except Exception as e:
        print(f"[ERROR PUSH MANTENIMIENTO] {e}")

    return db_notif