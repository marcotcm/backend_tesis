import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.fmea_analysis import FMEAAnalysis


async def get_by_id(db: AsyncSession, item_id: uuid.UUID) -> Optional[FMEAAnalysis]:
    result = await db.execute(select(FMEAAnalysis).where(FMEAAnalysis.id == item_id))
    return result.scalars().first()


async def get_by_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> list[FMEAAnalysis]:
    result = await db.execute(
        select(FMEAAnalysis)
        .where(FMEAAnalysis.equipment_id == equipment_id)
        .order_by(FMEAAnalysis.created_at.desc())
    )
    return list(result.scalars().all())


async def list_all(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[FMEAAnalysis]:
    result = await db.execute(
        select(FMEAAnalysis)
        .order_by(FMEAAnalysis.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def create(db: AsyncSession, data: dict) -> FMEAAnalysis:
    obj = FMEAAnalysis(**data)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def update(db: AsyncSession, obj: FMEAAnalysis, data: dict) -> FMEAAnalysis:
    for key, value in data.items():
        setattr(obj, key, value)
    await db.commit()
    await db.refresh(obj)
    return obj
