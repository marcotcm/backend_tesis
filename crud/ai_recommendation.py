import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai_recommendation import AIRecommendation


async def get_by_id(db: AsyncSession, item_id: uuid.UUID) -> Optional[AIRecommendation]:
    result = await db.execute(select(AIRecommendation).where(AIRecommendation.id == item_id))
    return result.scalars().first()


async def list_all(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[AIRecommendation]:
    result = await db.execute(
        select(AIRecommendation)
        .order_by(AIRecommendation.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def create(db: AsyncSession, data: dict) -> AIRecommendation:
    obj = AIRecommendation(**data)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def update(db: AsyncSession, obj: AIRecommendation, data: dict) -> AIRecommendation:
    for key, value in data.items():
        setattr(obj, key, value)
    await db.commit()
    await db.refresh(obj)
    return obj

