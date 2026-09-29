import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from crud import ai_correction as crud
from crud import ai_recommendation as crud_recommendation
from models.user import User
from schemas.ai_correction import AICorrectionCreate, AICorrectionUpdate


async def create(db: AsyncSession, data: AICorrectionCreate, user: User):
    """
    Registra una corrección humana para una recomendación de IA.

    La recomendación debe existir y estar aceptada o rechazada.
    Solo se permite una corrección por recomendación y el usuario
    corrector se obtiene del token autenticado.
    """
    recommendation = await crud_recommendation.get_by_id(db, data.recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="La recomendación no existe.")
    if recommendation.status not in ("Aceptada", "Rechazada"):
        raise HTTPException(status_code=409, detail="La recomendación debe estar resuelta antes de corregirse.")
    if await crud.get_by_recommendation(db, data.recommendation_id):
        raise HTTPException(status_code=409, detail="La recomendación ya tiene una corrección.")
    payload = data.model_dump()
    payload["corrected_by"] = user.id
    return await crud.create(db, payload)


async def get(db: AsyncSession, item_id: uuid.UUID):
    """Obtiene una corrección humana por UUID o devuelve 404."""
    obj = await crud.get_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Corrección no encontrada.")
    return obj


async def update(db: AsyncSession, item_id: uuid.UUID, data: AICorrectionUpdate):
    """Actualiza el texto de una corrección existente."""
    obj = await get(db, item_id)
    return await crud.update(db, obj, data.model_dump(exclude_unset=True))

