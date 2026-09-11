"""
Módulo CRUD para los mantenimientos.
"""

import uuid
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from models.maintenance import Maintenance


async def create_maintenance(db: AsyncSession, obj_in: dict) -> Maintenance:
    db_obj = Maintenance(**obj_in)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_maintenance_by_id(db: AsyncSession, maintenance_id: uuid.UUID) -> Optional[Maintenance]:
    result = await db.execute(select(Maintenance).where(Maintenance.id == maintenance_id))
    return result.scalars().first()


async def get_maintenances(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Maintenance]:
    result = await db.execute(select(Maintenance).order_by(Maintenance.created_at.desc()).offset(skip).limit(limit))
    return list(result.scalars().all())


async def get_maintenances_by_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> List[Maintenance]:
    result = await db.execute(
        select(Maintenance).where(Maintenance.equipment_id == equipment_id).order_by(Maintenance.created_at.desc())
    )
    return list(result.scalars().all())


async def update_maintenance(db: AsyncSession, db_obj: Maintenance, update_data: dict) -> Maintenance:
    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)

    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def deactivate_maintenance(db: AsyncSession, db_obj: Maintenance) -> Maintenance:
    db_obj.is_active = False
    await db.commit()
    await db.refresh(db_obj)
    return db_obj
