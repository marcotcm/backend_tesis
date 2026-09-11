"""
Módulo CRUD para los equipos/activos.
"""

import uuid
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from models.equipment import Equipment


async def create_equipment(db: AsyncSession, obj_in: dict) -> Equipment:
    db_obj = Equipment(**obj_in)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_equipment_by_id(db: AsyncSession, equipment_id: uuid.UUID) -> Optional[Equipment]:
    result = await db.execute(select(Equipment).where(Equipment.id == equipment_id))
    return result.scalars().first()


async def get_equipment_by_tag_number(db: AsyncSession, tag_number: str) -> Optional[Equipment]:
    result = await db.execute(select(Equipment).where(Equipment.tag_number == tag_number))
    return result.scalars().first()


async def get_equipments(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Equipment]:
    result = await db.execute(select(Equipment).order_by(Equipment.name).offset(skip).limit(limit))
    return list(result.scalars().all())


async def get_equipments_by_taxonomy(db: AsyncSession, taxonomy_id: uuid.UUID) -> List[Equipment]:
    result = await db.execute(
        select(Equipment).where(Equipment.taxonomy_id == taxonomy_id).order_by(Equipment.name)
    )
    return list(result.scalars().all())


async def update_equipment(db: AsyncSession, db_obj: Equipment, update_data: dict) -> Equipment:
    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)

    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def deactivate_equipment(db: AsyncSession, db_obj: Equipment) -> Equipment:
    db_obj.is_active = False
    await db.commit()
    await db.refresh(db_obj)
    return db_obj
