"""
Módulo CRUD para la taxonomía de equipos.
"""

import uuid
from typing import List, Optional
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.equipment import Equipment
from models.equipment_taxonomy import EquipmentTaxonomy

async def create_taxonomy(db: AsyncSession, obj_in: dict) -> EquipmentTaxonomy:
    db_obj = EquipmentTaxonomy(**obj_in)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_taxonomy_by_id(db: AsyncSession, taxonomy_id: uuid.UUID) -> Optional[EquipmentTaxonomy]:
    result = await db.execute(
        select(EquipmentTaxonomy).where(
            EquipmentTaxonomy.id == taxonomy_id,
            EquipmentTaxonomy.deleted_at.is_(None)
        )
    )
    return result.scalars().first()

async def get_taxonomies_by_name(
    db: AsyncSession, name: str
) -> List[EquipmentTaxonomy]:
    normalized_name = name.strip().casefold()
    result = await db.execute(
        select(EquipmentTaxonomy).where(
            func.lower(func.trim(EquipmentTaxonomy.name)) == normalized_name,
            EquipmentTaxonomy.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())

async def get_taxonomies(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[EquipmentTaxonomy]:
    result = await db.execute(
        select(EquipmentTaxonomy)
        .where(EquipmentTaxonomy.deleted_at.is_(None))
        .order_by(EquipmentTaxonomy.level)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())

async def get_taxonomies_by_parent(db: AsyncSession, parent_id: Optional[uuid.UUID]) -> List[EquipmentTaxonomy]:
    query = select(EquipmentTaxonomy).where(EquipmentTaxonomy.deleted_at.is_(None)).order_by(EquipmentTaxonomy.name)
    if parent_id is None:
        query = query.where(EquipmentTaxonomy.parent_id.is_(None))
    else:
        query = query.where(EquipmentTaxonomy.parent_id == parent_id)
        
    result = await db.execute(query)
    return list(result.scalars().all())

async def has_children(db: AsyncSession, taxonomy_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(EquipmentTaxonomy.id).where(
            EquipmentTaxonomy.parent_id == taxonomy_id,
            EquipmentTaxonomy.deleted_at.is_(None)
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None

async def has_equipments(db: AsyncSession, taxonomy_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(Equipment.id).where(
            Equipment.taxonomy_id == taxonomy_id,
            Equipment.deleted_at.is_(None)
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None

async def update_taxonomy(db: AsyncSession, db_obj: EquipmentTaxonomy, update_data: dict) -> EquipmentTaxonomy:
    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)

    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def delete_taxonomy(db: AsyncSession, db_obj: EquipmentTaxonomy) -> EquipmentTaxonomy:
    """Aplica soft delete al registro de taxonomía."""
    db_obj.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj