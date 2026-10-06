"""
Módulo CRUD para los equipos/activos.
"""

import uuid
from typing import List, Optional
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.equipment import Equipment

async def create_equipment(db: AsyncSession, obj_in: dict) -> Equipment:
    db_obj = Equipment(**obj_in)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_equipment_by_id(db: AsyncSession, equipment_id: uuid.UUID) -> Optional[Equipment]:
    result = await db.execute(
        select(Equipment).where(Equipment.id == equipment_id, Equipment.deleted_at.is_(None))
    )
    return result.scalars().first()

async def get_equipment_by_tag_number(db: AsyncSession, tag_number: str) -> Optional[Equipment]:
    """Busca tags actualmente asignados, ignorando los dados de baja."""
    result = await db.execute(
        select(Equipment).where(Equipment.tag_number == tag_number, Equipment.deleted_at.is_(None))
    )
    return result.scalars().first()

async def get_equipments(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Equipment]:
    result = await db.execute(
        select(Equipment)
        .where(Equipment.deleted_at.is_(None))
        .order_by(Equipment.name)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())

async def get_equipments_by_taxonomy(db: AsyncSession, taxonomy_id: uuid.UUID) -> List[Equipment]:
    result = await db.execute(
        select(Equipment)
        .where(Equipment.taxonomy_id == taxonomy_id, Equipment.deleted_at.is_(None))
        .order_by(Equipment.name)
    )
    return list(result.scalars().all())

async def get_all_equipments_by_taxonomy(
    db: AsyncSession, taxonomy_id: uuid.UUID
) -> List[Equipment]:
    """Obtiene todos los equipos de una taxonomía, incluidos los dados de baja."""
    result = await db.execute(
        select(Equipment)
        .where(Equipment.taxonomy_id == taxonomy_id)
        .order_by(Equipment.tag_number)
    )
    return list(result.scalars().all())

async def get_existing_equipment_tags(
    db: AsyncSession, tag_numbers: list[str]
) -> set[str]:
    if not tag_numbers:
        return set()
    result = await db.execute(
        select(Equipment.tag_number).where(Equipment.tag_number.in_(tag_numbers))
    )
    return set(result.scalars().all())

async def create_equipments_bulk(
    db: AsyncSession, records: list[dict]
) -> list[Equipment]:
    objects = [Equipment(**record) for record in records]
    try:
        db.add_all(objects)
        await db.flush()
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise
    return objects

async def update_equipment(db: AsyncSession, db_obj: Equipment, update_data: dict) -> Equipment:
    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)

    db_obj.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def deactivate_equipment(db: AsyncSession, db_obj: Equipment) -> Equipment:
    db_obj.is_active = False
    db_obj.deleted_at = datetime.now(timezone.utc)
    db_obj.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj