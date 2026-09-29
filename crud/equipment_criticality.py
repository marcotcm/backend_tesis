import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.equipment_criticality import EquipmentCriticality


async def get_by_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> Optional[EquipmentCriticality]:
    result = await db.execute(
        select(EquipmentCriticality).where(
            EquipmentCriticality.equipment_id == equipment_id,
        )
    )
    return result.scalars().first()

async def list_all(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[EquipmentCriticality]:
    result = await db.execute(
        select(EquipmentCriticality)
        .order_by(EquipmentCriticality.evaluated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, item_id: uuid.UUID) -> Optional[EquipmentCriticality]:
    result = await db.execute(
        select(EquipmentCriticality).where(
            EquipmentCriticality.id == item_id,
        )
    )
    return result.scalars().first()


async def create(db: AsyncSession, data: dict) -> EquipmentCriticality:
    obj = EquipmentCriticality(**data)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def update(db: AsyncSession, obj: EquipmentCriticality, data: dict) -> EquipmentCriticality:
    for key, value in data.items():
        setattr(obj, key, value)
    await db.commit()
    await db.refresh(obj)
    return obj

