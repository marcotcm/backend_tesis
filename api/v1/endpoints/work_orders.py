"""
Rutas y Controladores de la API para el Módulo de Órdenes de Trabajo (Sistema RCM).

Define los endpoints RESTful protegidos y documentados para Swagger/OpenAPI,
gestionando el ciclo de vida, asignaciones y despachos de mantenimiento en planta.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from core.security import get_current_user, RoleChecker
from models.user import User, UserRole
from models.work_orders import WorkOrderStatus
from schemas.work_orders import WorkOrderCreate, WorkOrderUpdate, WorkOrderResponse
from services import work_orders as wo_service

router = APIRouter()

@router.post("/", response_model=WorkOrderResponse, status_code=status.HTTP_201_CREATED)
async def crear_orden_de_trabajo(
    wo_in: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** POST /api/v1/ordenes-trabajo/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Emite un ticket de trabajo derivado de un plan de mantenimiento (preventivo, correctivo o IA).
    * **Resultado:** Despacha la orden en el sistema e inyecta el ID del usuario creador para trazabilidad de planificación.
    """
    return await wo_service.create_new_work_order(db=db, wo_in=wo_in, current_user=current_user)

@router.get("/", response_model=List[WorkOrderResponse], status_code=status.HTTP_200_OK)
async def listar_ordenes_globales(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/ordenes-trabajo/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Visualiza la matriz completa de órdenes de trabajo emitidas en toda la planta.
    * **Resultado:** Devuelve un arreglo JSON paginado de los tickets ordenados desde el más reciente.
    """
    return await wo_service.get_all_work_orders(db=db, skip=skip, limit=limit)

@router.get("/estado/{status}", response_model=List[WorkOrderResponse], status_code=status.HTTP_200_OK)
async def listar_ordenes_por_estado(
    status: WorkOrderStatus,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/ordenes-trabajo/estado/{status}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Alimentación vital para tableros Kanban. Filtra órdenes por 'Pendiente', 'En Proceso', etc.
    * **Resultado:** Lista el subconjunto de tickets que se encuentran actualmente en el estado solicitado.
    """
    return await wo_service.get_wos_by_status(db=db, wo_status=status, skip=skip, limit=limit)

@router.get("/mantenimiento/{maintenance_id}", response_model=List[WorkOrderResponse], status_code=status.HTTP_200_OK)
async def historial_ordenes_por_plan(
    maintenance_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/ordenes-trabajo/mantenimiento/{maintenance_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Evalúa el nivel de cumplimiento y repetición de un plan maestro de mantenimiento específico.
    * **Resultado:** Retorna el historial íntegro de ejecuciones asociadas a la pauta de mantenimiento consultada.
    """
    return await wo_service.get_wos_by_maintenance(db=db, maintenance_id=maintenance_id, skip=skip, limit=limit)

@router.get("/asignado/{user_id}", response_model=List[WorkOrderResponse], status_code=status.HTTP_200_OK)
async def ordenes_asignadas_a_tecnico(
    user_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/ordenes-trabajo/asignado/{user_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Extrae la bandeja de entrada o backlog de tareas pendientes o realizadas por un trabajador específico.
    * **Resultado:** Devuelve el inventario de OTs en las que el técnico figura como responsable (`assigned_to`).
    """
    return await wo_service.get_wos_by_assignee(db=db, user_id=user_id, skip=skip, limit=limit)

@router.get("/creado-por/{user_id}", response_model=List[WorkOrderResponse], status_code=status.HTTP_200_OK)
async def ordenes_creadas_por_planificador(
    user_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/ordenes-trabajo/creado-por/{user_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Auditoría de gestión. Permite revisar el volumen de tickets despachados por un supervisor/planificador.
    * **Resultado:** Devuelve la lista de órdenes generadas (`created_by`) por el usuario consultado.
    """
    return await wo_service.get_wos_by_creator(db=db, user_id=user_id, skip=skip, limit=limit)

@router.get("/{id}", response_model=WorkOrderResponse, status_code=status.HTTP_200_OK)
async def obtener_orden_por_id(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/ordenes-trabajo/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Consulta el expediente aislado de un ticket (fechas de inicio, cierre, y anotaciones del técnico).
    * **Resultado:** Expone el registro detallado de la orden de trabajo.
    """
    return await wo_service.get_work_order_or_404(db, id)

@router.patch("/{id}", response_model=WorkOrderResponse, status_code=status.HTTP_200_OK)
async def actualizar_orden(
    id: uuid.UUID,
    wo_in: WorkOrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** PATCH /api/v1/ordenes-trabajo/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Creador de la orden, Técnico Asignado o Administrador
    * **Uso:** Cambia el ticket de estado (Ej. a 'En Proceso') o añade los tiempos reales y notas post-ejecución.
    * **Resultado:** Inyecta las modificaciones preservando la cadena de autorización; la fecha de actualización (`updated_at`) cambia automáticamente.
    """
    return await wo_service.update_work_order_record(db=db, wo_id=id, wo_in=wo_in, current_user=current_user)

@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def anular_orden(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** DELETE /api/v1/ordenes-trabajo/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Creador de la Orden o Administrador (`admin`)
    * **Uso:** Ejecuta un Soft-Delete lógico. Pasa el ticket al estado 'Cancelado' en vez de borrar el registro físico.
    * **Resultado:** Mantiene intacta la trazabilidad y la integridad referencial, bloqueando la cancelación si la orden ya figura como Terminada.
    """
    return await wo_service.cancel_work_order(db=db, wo_id=id, current_user=current_user)