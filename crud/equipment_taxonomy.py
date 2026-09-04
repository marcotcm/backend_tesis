"""
Módulo CRUD para la taxonomía de equipos.
"""

import uuid
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from models.equipment_taxonomy import EquipmentTaxonomy


async def create_taxonomy(db: AsyncSession, obj_in: dict) -> EquipmentTaxonomy:
    db_obj = EquipmentTaxonomy(**obj_in)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_taxonomy_by_id(db: AsyncSession, taxonomy_id: uuid.UUID) -> Optional[EquipmentTaxonomy]:
    result = await db.execute(select(EquipmentTaxonomy).where(EquipmentTaxonomy.id == taxonomy_id))
    return result.scalars().first()


async def get_taxonomies(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[EquipmentTaxonomy]:
    result = await db.execute(
        select(EquipmentTaxonomy).order_by(EquipmentTaxonomy.level).offset(skip).limit(limit)
    )
    return list(result.scalars().all())


async def get_taxonomies_by_parent(db: AsyncSession, parent_id: Optional[uuid.UUID]) -> List[EquipmentTaxonomy]:
    if parent_id is None:
        result = await db.execute(
            select(EquipmentTaxonomy).where(EquipmentTaxonomy.parent_id.is_(None)).order_by(EquipmentTaxonomy.name)
        )
    else:
        result = await db.execute(
            select(EquipmentTaxonomy).where(EquipmentTaxonomy.parent_id == parent_id).order_by(EquipmentTaxonomy.name)
        )
    return list(result.scalars().all())


async def update_taxonomy(db: AsyncSession, db_obj: EquipmentTaxonomy, update_data: dict) -> EquipmentTaxonomy:
    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)

    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def delete_taxonomy(db: AsyncSession, db_obj: EquipmentTaxonomy) -> None:
    await db.delete(db_obj)
    await db.commit()
