"""
Capa de Acceso a Datos (CRUD) para Órdenes de Trabajo.
Maneja las transacciones físicas con la tabla 'public.work_orders'.
"""

import uuid
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.work_orders import WorkOrder, WorkOrderStatus

async def create_work_order(db: AsyncSession, obj_in: dict) -> WorkOrder:
    """Inserta una nueva OT en la base de datos."""
    db_obj = WorkOrder(**obj_in)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_work_orders(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[WorkOrder]:
    """Obtiene el inventario completo de OTs, ordenado por fecha de creación."""
    result = await db.execute(
        select(WorkOrder).order_by(WorkOrder.created_at.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all()

async def get_work_order_by_id(db: AsyncSession, wo_id: uuid.UUID) -> Optional[WorkOrder]:
    """Obtiene una orden de trabajo por su identificador primario."""
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    return result.scalar_one_or_none()

async def get_work_orders_by_maintenance(
    db: AsyncSession, maintenance_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[WorkOrder]:
    """Obtiene todas las órdenes emitidas a partir de un plan maestro de mantenimiento específico."""
    result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.maintenance_id == maintenance_id)
        .order_by(WorkOrder.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def get_work_orders_by_assignee(
    db: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[WorkOrder]:
    """Extrae la cola de trabajo asignada a un técnico particular."""
    result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.assigned_to == user_id)
        .order_by(WorkOrder.scheduled_for.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def get_work_orders_by_creator(
    db: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[WorkOrder]:
    """Lista las órdenes emitidas por un planificador (created_by)."""
    result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.created_by == user_id)
        .order_by(WorkOrder.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def get_work_orders_by_status(
    db: AsyncSession, status: WorkOrderStatus, skip: int = 0, limit: int = 100
) -> List[WorkOrder]:
    """Filtra las OTs por su estado en el Kanban (Pendiente, En Proceso, etc.)."""
    result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.status == status)
        .order_by(WorkOrder.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def update_work_order(db: AsyncSession, db_obj: WorkOrder, update_data: dict) -> WorkOrder:
    """Aplica actualizaciones parciales a la orden (notas, cambios de estado o fechas)."""
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj