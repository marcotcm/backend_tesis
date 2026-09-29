import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from crud import ai_recommendation as crud
from crud import equipment as crud_equipment
from models.user import User
from schemas.ai_recommendation import AIRecommendationCreate, AIRecommendationStatusUpdate, AIRecommendationUpdate


async def create(db: AsyncSession, data: AIRecommendationCreate):
    """
    Registra una recomendación de IA para un equipo existente.

    Actualmente la recomendación llega desde la API; la generación
    automática mediante un modelo de IA se integrará posteriormente.
    """
    if not await crud_equipment.get_equipment_by_id(db, data.equipment_id):
        raise HTTPException(status_code=404, detail="El equipo no existe.")
    return await crud.create(db, data.model_dump())


async def get(db: AsyncSession, item_id: uuid.UUID):
    """Obtiene una recomendación por UUID o devuelve 404."""
    obj = await crud.get_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Recomendación no encontrada.")
    return obj


async def update(db: AsyncSession, item_id: uuid.UUID, data: AIRecommendationUpdate):
    """Actualiza el contenido editable de una recomendación existente."""
    return await crud.update(db, await get(db, item_id), data.model_dump(exclude_unset=True))


async def set_status(db: AsyncSession, item_id: uuid.UUID, data: AIRecommendationStatusUpdate, user: User):
    """
    Cambia el estado de una recomendación.

    Al aceptarla o rechazarla registra quién resolvió la recomendación
    y cuándo ocurrió; al volver a pendiente limpia esos datos.
    """
    obj = await get(db, item_id)
    payload = {"status": data.status}
    if data.status in ("Aceptada", "Rechazada"):
        payload.update(resolved_by=user.id, resolved_at=datetime.now(timezone.utc))
    else:
        payload.update(resolved_by=None, resolved_at=None)
    return await crud.update(db, obj, payload)

