import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from crud import equipment as crud_equipment
from crud import equipment_criticality as crud
from models.user import User
from schemas.equipment_criticality import EquipmentCriticalityCreate, EquipmentCriticalityUpdate


async def create(db: AsyncSession, data: EquipmentCriticalityCreate, user: User):
    """
    Crea la evaluación de criticidad de un equipo.

    Comprueba que el equipo exista, impide evaluaciones duplicadas
    y registra automáticamente el usuario evaluador.
    """
    if not await crud_equipment.get_equipment_by_id(db, data.equipment_id):
        raise HTTPException(status_code=404, detail="El equipo no existe.")
    if await crud.get_by_equipment(db, data.equipment_id):
        raise HTTPException(status_code=409, detail="El equipo ya tiene una criticidad.")
    payload = data.model_dump()
    payload["evaluated_by"] = user.id
    return await crud.create(db, payload)


async def get(db: AsyncSession, item_id: uuid.UUID):
    """Obtiene una evaluación de criticidad por UUID o devuelve 404."""
    obj = await crud.get_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Criticidad no encontrada.")
    return obj


async def update(db: AsyncSession, item_id: uuid.UUID, data: EquipmentCriticalityUpdate, user: User):
    """
    Actualiza una evaluación de criticidad y registra la nueva evaluación.

    El usuario autenticado queda almacenado como evaluador junto con
    la fecha y hora de la actualización.
    """
    obj = await get(db, item_id)
    payload = data.model_dump(exclude_unset=True)
    payload["evaluated_by"] = user.id
    payload["evaluated_at"] = datetime.now(timezone.utc)
    return await crud.update(db, obj, payload)

