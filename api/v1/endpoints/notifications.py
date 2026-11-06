"""
Rutas y Controladores de la API para el Módulo de Notificaciones (Sistema RCM).

Define los endpoints RESTful para la consulta de notificaciones por parte de los usuarios,
marcado de lectura y el endpoint de conexión WebSocket para la reactividad en tiempo real.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, Query, status, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from core.security import get_current_user
from models.user import User, UserRole
from schemas.notification import NotificationResponse
from crud import notification as crud_notification
from services.notification import manager

router = APIRouter()

@router.get("/me", response_model=List[NotificationResponse], status_code=status.HTTP_200_OK)
async def obtener_mis_notificaciones(
    skip: int = Query(0, ge=0, description="Número de registros a omitir para paginación"),
    limit: int = Query(50, ge=1, le=100, description="Límite de registros a recuperar"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/notificaciones/me
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Obtiene el historial de notificaciones dirigidas al usuario en sesión, así como las alertas globales del sistema.
    * **Resultado:** Retorna una lista paginada de notificaciones (alertas de métricas, análisis IA, OTs) ordenadas de más recientes a más antiguas.
    """
    return await crud_notification.get_user_notifications(db=db, user_id=current_user.id, skip=skip, limit=limit)


@router.patch("/{id}/leer", response_model=NotificationResponse, status_code=status.HTTP_200_OK)
async def marcar_notificacion_como_leida(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** PATCH /api/v1/notificaciones/{id}/leer
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Propietario de la notificación o espectador de notificación global
    * **Uso:** Actualiza el estado de una notificación específica para quitarle la marca de "No leída" en la interfaz.
    * **Resultado:** Cambia el flag `is_read` a `true` en la base de datos y retorna el registro actualizado. Retorna 404 si no existe o no le pertenece.
    """
    notif = await crud_notification.mark_notification_as_read(db=db, notification_id=id, user_id=current_user.id)
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificación no encontrada o no tienes permisos para acceder a ella."
        )
    return notif


@router.websocket("/ws")
async def websocket_notificaciones(websocket: WebSocket):
    """
    * **Ruta:** WS /api/v1/notificaciones/ws
    * **Token:** Requiere (Usualmente administrado en el handshake del cliente o interceptor)
    * **Nivel de permiso:** Cliente autenticado
    * **Uso:** Establece un canal TCP bidireccional permanente (WebSockets) entre el Frontend/App Móvil y el backend Heimdall.
    * **Resultado:** Permite que el servidor despache instantáneamente eventos JSON (ej. `"event": "new_alert"`) sin que el cliente tenga que hacer polling constante, optimizando recursos y tiempos de respuesta en campo.
    """
    await manager.connect(websocket)
    try:
        while True:
            # El bucle mantiene la conexión viva. Se puede usar para recibir pings del cliente.
            data = await websocket.receive_text()
            # Opcional: procesar mensajes recibidos desde el cliente si fuera necesario
    except WebSocketDisconnect:
        manager.disconnect(websocket)