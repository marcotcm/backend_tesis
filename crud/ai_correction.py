import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai_correction import AICorrection


async def get_by_id(db: AsyncSession, item_id: uuid.UUID) -> Optional[AICorrection]:
    result = await db.execute(select(AICorrection).where(AICorrection.id == item_id))
    return result.scalars().first()


async def get_by_recommendation(db: AsyncSession, recommendation_id: uuid.UUID) -> Optional[AICorrection]:
    result = await db.execute(
        select(AICorrection).where(AICorrection.recommendation_id == recommendation_id)
    )
    return result.scalars().first()


async def list_all(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[AICorrection]:
    result = await db.execute(
        select(AICorrection)
        .order_by(AICorrection.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def create(db: AsyncSession, data: dict) -> AICorrection:
    obj = AICorrection(**data)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def update(db: AsyncSession, obj: AICorrection, data: dict) -> AICorrection:
    for key, value in data.items():
        setattr(obj, key, value)
    await db.commit()
    await db.refresh(obj)
    return obj

