"""
Capa de Servicios y Reglas de Negocio para Órdenes de Trabajo.

Asegura autorizaciones, audita los cambios de estado y maneja la cancelación lógica (Soft Delete)
de las órdenes para no romper el historial de trazabilidad RCM.
"""

import uuid
from typing import List
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from crud import work_orders as crud_wo
from schemas.work_orders import WorkOrderCreate, WorkOrderUpdate
from models.work_orders import WorkOrder, WorkOrderStatus
from models.user import User, UserRole

async def create_new_work_order(db: AsyncSession, wo_in: WorkOrderCreate, current_user: User) -> WorkOrder:
    """Emite una nueva orden de trabajo, vinculándola criptográficamente al planificador en sesión."""
    wo_data = wo_in.model_dump()
    wo_data["created_by"] = current_user.id
    
    try:
        return await crud_wo.create_work_order(db, obj_in=wo_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al emitir la orden de trabajo: {str(e)}"
        )

async def get_all_work_orders(db: AsyncSession, skip: int, limit: int) -> List[WorkOrder]:
    return await crud_wo.get_work_orders(db, skip=skip, limit=limit)

async def get_work_order_or_404(db: AsyncSession, wo_id: uuid.UUID) -> WorkOrder:
    wo = await crud_wo.get_work_order_by_id(db, wo_id)
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orden de trabajo no encontrada.")
    return wo

async def get_wos_by_maintenance(db: AsyncSession, maintenance_id: uuid.UUID, skip: int, limit: int) -> List[WorkOrder]:
    return await crud_wo.get_work_orders_by_maintenance(db, maintenance_id, skip, limit)

async def get_wos_by_assignee(db: AsyncSession, user_id: uuid.UUID, skip: int, limit: int) -> List[WorkOrder]:
    return await crud_wo.get_work_orders_by_assignee(db, user_id, skip, limit)

async def get_wos_by_creator(db: AsyncSession, user_id: uuid.UUID, skip: int, limit: int) -> List[WorkOrder]:
    return await crud_wo.get_work_orders_by_creator(db, user_id, skip, limit)

async def get_wos_by_status(db: AsyncSession, wo_status: WorkOrderStatus, skip: int, limit: int) -> List[WorkOrder]:
    return await crud_wo.get_work_orders_by_status(db, wo_status, skip, limit)

async def update_work_order_record(
    db: AsyncSession, wo_id: uuid.UUID, wo_in: WorkOrderUpdate, current_user: User
) -> WorkOrder:
    """
    Aplica cambios a una OT. 
    Regla de negocio: Un técnico normal solo puede actualizar las órdenes que le han sido asignadas.
    Administradores y auditores pueden modificar cualquier orden.
    """
    db_wo = await get_work_order_or_404(db, wo_id)
    
    if current_user.role == UserRole.rcm_engineer and db_wo.assigned_to != current_user.id and db_wo.created_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes modificar las órdenes de trabajo que has creado o que te han sido asignadas."
        )
        
    update_data = wo_in.model_dump(exclude_unset=True)
    if not update_data:
        return db_wo
        
    return await crud_wo.update_work_order(db, db_obj=db_wo, update_data=update_data)

async def cancel_work_order(db: AsyncSession, wo_id: uuid.UUID, current_user: User) -> dict:
    """
    Soft-Delete Operativo: En lugar de borrar la fila (lo que rompería métricas de planificación), 
    se cambia el estado a 'Cancelado'. Restringido a planificadores (creador) y administradores.
    """
    db_wo = await get_work_order_or_404(db, wo_id)
    
    if current_user.role != UserRole.admin and db_wo.created_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para cancelar (anular) esta orden de trabajo."
        )
        
    if db_wo.status == WorkOrderStatus.terminado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede cancelar una orden de trabajo que ya ha sido terminada y entregada."
        )
        
    await crud_wo.update_work_order(db, db_obj=db_wo, update_data={"status": WorkOrderStatus.cancelado})
    
    return {"detail": "Orden de trabajo cancelada satisfactoriamente (Baja lógica)."}