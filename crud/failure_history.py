"""
Capa de Acceso a Datos (CRUD) para Historial de Fallas.
"""

import uuid
from typing import List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.failure_history import FailureHistory

async def create_failure(db: AsyncSession, obj_in: dict) -> FailureHistory:
    """Registra una nueva avería en la base de datos."""
    db_obj = FailureHistory(**obj_in)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_failures(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[FailureHistory]:
    """Obtiene el historial global de averías."""
    result = await db.execute(
        select(FailureHistory).order_by(FailureHistory.failure_date.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all()

async def get_failure_by_id(db: AsyncSession, failure_id: uuid.UUID) -> Optional[FailureHistory]:
    """Obtiene un reporte de falla específico."""
    result = await db.execute(select(FailureHistory).where(FailureHistory.id == failure_id))
    return result.scalar_one_or_none()

async def get_failures_by_equipment(
    db: AsyncSession, equipment_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[FailureHistory]:
    """Obtiene el historial de fallas de un equipo particular."""
    result = await db.execute(
        select(FailureHistory)
        .where(FailureHistory.equipment_id == equipment_id)
        .order_by(FailureHistory.failure_date.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def get_failures_by_reporter(
    db: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[FailureHistory]:
    """Obtiene las fallas reportadas por un usuario específico."""
    result = await db.execute(
        select(FailureHistory)
        .where(FailureHistory.reported_by == user_id)
        .order_by(FailureHistory.failure_date.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def get_failures_by_date_range(
    db: AsyncSession, 
    start_date: datetime, 
    end_date: datetime, 
    equipment_id: Optional[uuid.UUID] = None, 
    skip: int = 0, 
    limit: int = 100
) -> List[FailureHistory]:
    """Filtra fallas por rango temporal."""
    query = select(FailureHistory).where(
        FailureHistory.failure_date >= start_date,
        FailureHistory.failure_date <= end_date
    )
    
    if equipment_id:
        query = query.where(FailureHistory.equipment_id == equipment_id)
        
    result = await db.execute(
        query.order_by(FailureHistory.failure_date.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def update_failure(db: AsyncSession, db_obj: FailureHistory, update_data: dict) -> FailureHistory:
    """Actualiza campos permitidos de un reporte."""
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def delete_failure(db: AsyncSession, db_obj: FailureHistory) -> None:
    """Eliminación física del reporte (Hard Delete)."""
    await db.delete(db_obj)
    await db.commit()