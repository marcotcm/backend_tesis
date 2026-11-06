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
import uuid

from crud.notification import create_notification
from schemas.notification import NotificationCreate
from services import user_push_token as push_service

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
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message, default=str))
            except Exception:
                pass # Ignorar conexiones caídas

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
    } for token in tokens]

    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                "https://exp.host/--/api/v2/push/send",
                json=messages,
                headers={"Accept": "application/json", "Accept-encoding": "gzip, deflate", "Content-Type": "application/json"}
            )
        except Exception as e:
            print(f"[ERROR PUSH] Fallo enviando notificación Expo: {e}")

# ==============================================================================
# TRIGGERS AUTOMÁTICOS (Llamados desde equipment_metrics, ai_predictive, etc.)
# ==============================================================================

async def trigger_global_alert(db: AsyncSession, title: str, message: str):
    """1. Se dispara sola si se sube una MÉTRICA MALA (Fuera de umbrales)"""
    notif_data = NotificationCreate(title=title, message=message, notification_type="alerta")
    db_notif = await create_notification(db, notif_data)
    
    await manager.broadcast({"event": "new_alert", "data": {"id": db_notif.id, "title": title, "message": message, "type": "alerta"}})
    
    tokens_db = await push_service.list_all_tokens(db) 
    tokens = [t.token for t in tokens_db]
    await send_expo_push_notifications(tokens, title, message)
    return db_notif

async def notify_ai_analysis_ready(db: AsyncSession, title: str, message: str, user_id: Optional[uuid.UUID] = None):
    """2. Se dispara sola cuando la IA termina de generar un ANÁLISIS o PLAN"""
    notif_data = NotificationCreate(title=title, message=message, notification_type="ia", user_id=user_id)
    db_notif = await create_notification(db, notif_data)
    
    await manager.broadcast({"event": "ai_analysis_ready", "data": {"id": db_notif.id, "title": title, "type": "ia"}})
    
    if user_id:
        tokens_db = await push_service.list_user_tokens(db, user_id=user_id)
    else:
        tokens_db = await push_service.list_all_tokens(db)
        
    tokens = [t.token for t in tokens_db]
    await send_expo_push_notifications(tokens, title, message)
    return db_notif

async def notify_work_order_assignment(db: AsyncSession, user_id: uuid.UUID, title: str, message: str):
    """3. Se dispara sola cuando se asigna una ORDEN DE TRABAJO a un técnico"""
    notif_data = NotificationCreate(title=title, message=message, notification_type="orden_trabajo", user_id=user_id)
    db_notif = await create_notification(db, notif_data)
    
    await manager.broadcast({"event": "work_order_assigned", "data": {"user_id": user_id, "title": title}})
    
    tokens_db = await push_service.list_user_tokens(db, user_id=user_id)
    tokens = [t.token for t in tokens_db]
    await send_expo_push_notifications(tokens, title, message)
    return db_notif

async def notify_new_maintenance(db: AsyncSession, title: str, message: str):
    """4. Se dispara sola cuando se inicia un NUEVO MANTENIMIENTO"""
    notif_data = NotificationCreate(title=title, message=message, notification_type="sistema")
    db_notif = await create_notification(db, notif_data)
    
    await manager.broadcast({"event": "new_maintenance", "data": {"id": db_notif.id, "title": title}})
    
    tokens_db = await push_service.list_all_tokens(db)
    tokens = [t.token for t in tokens_db]
    await send_expo_push_notifications(tokens, title, message)
    return db_notif