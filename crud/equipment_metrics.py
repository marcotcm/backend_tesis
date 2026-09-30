"""
Capa de Acceso a Datos (CRUD) para el historial de métricas.
"""

import uuid
from typing import List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.equipment_metrics import EquipmentMetricHistory

async def create_metric(db: AsyncSession, obj_in: dict) -> EquipmentMetricHistory:
    """Inserta una nueva lectura en la base de datos."""
    db_obj = EquipmentMetricHistory(**obj_in)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_metrics(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[EquipmentMetricHistory]:
    """Obtiene el historial global de métricas paginado."""
    result = await db.execute(
        select(EquipmentMetricHistory).order_by(EquipmentMetricHistory.recorded_at.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all()

async def get_metric_by_id(db: AsyncSession, metric_id: uuid.UUID) -> Optional[EquipmentMetricHistory]:
    """Busca un registro específico por su ID."""
    result = await db.execute(select(EquipmentMetricHistory).where(EquipmentMetricHistory.id == metric_id))
    return result.scalar_one_or_none()

async def get_metrics_by_equipment(
    db: AsyncSession, equipment_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[EquipmentMetricHistory]:
    """Obtiene la tendencia/historial de lecturas para un equipo específico."""
    result = await db.execute(
        select(EquipmentMetricHistory)
        .where(EquipmentMetricHistory.equipment_id == equipment_id)
        .order_by(EquipmentMetricHistory.recorded_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def get_metrics_by_user(
    db: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[EquipmentMetricHistory]:
    """Obtiene todas las lecturas ingresadas por un técnico específico."""
    result = await db.execute(
        select(EquipmentMetricHistory)
        .where(EquipmentMetricHistory.recorded_by == user_id)
        .order_by(EquipmentMetricHistory.recorded_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def get_metrics_by_date_range(
    db: AsyncSession, 
    start_date: datetime, 
    end_date: datetime, 
    equipment_id: Optional[uuid.UUID] = None, 
    skip: int = 0, 
    limit: int = 100
) -> List[EquipmentMetricHistory]:
    """Filtra el historial por rango de fechas, opcionalmente anidado a un equipo."""
    query = select(EquipmentMetricHistory).where(
        EquipmentMetricHistory.recorded_at >= start_date,
        EquipmentMetricHistory.recorded_at <= end_date
    )
    
    if equipment_id:
        query = query.where(EquipmentMetricHistory.equipment_id == equipment_id)
        
    result = await db.execute(
        query.order_by(EquipmentMetricHistory.recorded_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def update_metric(db: AsyncSession, db_obj: EquipmentMetricHistory, update_data: dict) -> EquipmentMetricHistory:
    """Actualiza parcialmente un registro de métrica (usualmente solo notas)."""
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def delete_metric(db: AsyncSession, db_obj: EquipmentMetricHistory) -> None:
    """Elimina permanentemente un registro (Hard Delete). Reservado para purga administrativa."""
    await db.delete(db_obj)
    await db.commit()