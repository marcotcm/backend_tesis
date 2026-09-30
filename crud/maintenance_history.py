"""
Capa de Acceso a Datos (CRUD) para Historial de Mantenimientos.
"""

import uuid
from typing import List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.maintenance_history import MaintenanceHistory

async def create_record(db: AsyncSession, obj_in: dict) -> MaintenanceHistory:
    db_obj = MaintenanceHistory(**obj_in)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_all_records(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[MaintenanceHistory]:
    result = await db.execute(
        select(MaintenanceHistory).order_by(MaintenanceHistory.execution_date.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all()

async def get_record_by_id(db: AsyncSession, record_id: uuid.UUID) -> Optional[MaintenanceHistory]:
    result = await db.execute(select(MaintenanceHistory).where(MaintenanceHistory.id == record_id))
    return result.scalar_one_or_none()

async def get_records_by_equipment(db: AsyncSession, equipment_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[MaintenanceHistory]:
    result = await db.execute(
        select(MaintenanceHistory)
        .where(MaintenanceHistory.equipment_id == equipment_id)
        .order_by(MaintenanceHistory.execution_date.desc())
        .offset(skip).limit(limit)
    )
    return result.scalars().all()

async def get_records_by_executor(db: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[MaintenanceHistory]:
    result = await db.execute(
        select(MaintenanceHistory)
        .where(MaintenanceHistory.executed_by == user_id)
        .order_by(MaintenanceHistory.execution_date.desc())
        .offset(skip).limit(limit)
    )
    return result.scalars().all()

async def get_records_by_work_order(db: AsyncSession, wo_id: uuid.UUID) -> List[MaintenanceHistory]:
    result = await db.execute(
        select(MaintenanceHistory).where(MaintenanceHistory.work_order_id == wo_id)
    )
    return result.scalars().all()

async def get_records_by_failure(db: AsyncSession, failure_id: uuid.UUID) -> List[MaintenanceHistory]:
    result = await db.execute(
        select(MaintenanceHistory).where(MaintenanceHistory.failure_id == failure_id)
    )
    return result.scalars().all()

async def get_records_by_dates(
    db: AsyncSession, start_date: datetime, end_date: datetime, equipment_id: Optional[uuid.UUID] = None, skip: int = 0, limit: int = 100
) -> List[MaintenanceHistory]:
    query = select(MaintenanceHistory).where(
        MaintenanceHistory.execution_date >= start_date,
        MaintenanceHistory.execution_date <= end_date
    )
    if equipment_id:
        query = query.where(MaintenanceHistory.equipment_id == equipment_id)
        
    result = await db.execute(query.order_by(MaintenanceHistory.execution_date.desc()).offset(skip).limit(limit))
    return result.scalars().all()

async def update_record(db: AsyncSession, db_obj: MaintenanceHistory, update_data: dict) -> MaintenanceHistory:
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def delete_record(db: AsyncSession, db_obj: MaintenanceHistory) -> None:
    await db.delete(db_obj)
    await db.commit()