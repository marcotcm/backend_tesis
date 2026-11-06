"""
Rutas y Controladores de la API para el Módulo de Notificaciones (Sistema RCM).

Define los endpoints RESTful para la creación manual, consulta, 
marcado de lectura y el endpoint de conexión WebSocket para la reactividad en tiempo real.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, Query, status, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.session import get_db
from core.security import get_current_user, RoleChecker
from models.user import User, UserRole
from models.notification import Notification
from schemas.notification import NotificationCreate, NotificationResponse
from crud import notification as crud_notification
from services.notification import manager, send_expo_push_notifications
from services import user_push_token as push_service

router = APIRouter()

@router.post("/", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
async def crear_notificacion_manual(
    notif_in: NotificationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.admin, UserRole.technical_auditor]))
):
    """
    * **Ruta:** POST /api/v1/notificaciones/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Administrador o Auditor Técnico
    * **Uso:** Permite a un administrador crear y disparar una notificación de forma manual (ej. un aviso de mantenimiento general programado).
    * **Resultado:** Guarda la notificación en la base de datos, la emite por WebSockets en tiempo real y dispara el Push de Expo.
    """
    # 1. Guardar en BD
    notif = await crud_notification.create_notification(db=db, obj_in=notif_in)
    
    # 2. Emitir por WebSocket
    await manager.broadcast({
        "event": "new_notification", 
        "data": {"id": notif.id, "title": notif.title, "type": notif.notification_type}
    })
    
    # 3. Disparar Push Notification
    if notif_in.user_id:
        tokens_db = await push_service.list_user_tokens(db, user_id=notif_in.user_id)
    else:
        tokens_db = await push_service.list_all_tokens(db)
        
    tokens = [t.token for t in tokens_db]
    await send_expo_push_notifications(tokens, notif.title, notif.message)
    
    return notif


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
    * **Uso:** Obtiene el historial de notificaciones dirigidas al usuario en sesión, así como las alertas globales del sistema (user_id nulo).
    * **Resultado:** Retorna una lista paginada de notificaciones ordenadas de más recientes a más antiguas.
    """
    return await crud_notification.get_user_notifications(db=db, user_id=current_user.id, skip=skip, limit=limit)


@router.get("/", response_model=List[NotificationResponse], status_code=status.HTTP_200_OK)
async def listar_todas_las_notificaciones(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.admin]))
):
    """
    * **Ruta:** GET /api/v1/notificaciones/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Administrador (`admin`)
    * **Uso:** Consulta el listado completo e histórico de todas las notificaciones emitidas por el sistema (auditoría).
    * **Resultado:** Retorna el arreglo JSON con todas las notificaciones registradas.
    """
    stmt = select(Notification).order_by(Notification.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


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
    * **Uso:** Actualiza el estado de una notificación específica para quitarle la marca de "No leída" en la interfaz de la App/Web.
    * **Resultado:** Cambia el flag `is_read` a `true` en la base de datos y retorna el registro actualizado.
    """
    notif = await crud_notification.mark_notification_as_read(db=db, notification_id=id, user_id=current_user.id)
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificación no encontrada o no tienes permisos para acceder a ella."
        )
    return notif


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def eliminar_notificacion(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.admin]))
):
    """
    * **Ruta:** DELETE /api/v1/notificaciones/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Administrador (`admin`)
    * **Uso:** Elimina físicamente un registro de notificación de la base de datos (limpieza de bitácora).
    * **Resultado:** Borra la notificación y retorna mensaje de éxito.
    """
    stmt = select(Notification).where(Notification.id == id)
    result = await db.execute(stmt)
    db_notif = result.scalar_one_or_none()
    
    if not db_notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notificación no encontrada.")
        
    await db.delete(db_notif)
    await db.commit()
    return {"detail": "Notificación eliminada permanentemente del sistema."}


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
            # El bucle mantiene la conexión viva. Se usa para escuchar respuestas o "pings" del cliente.
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)