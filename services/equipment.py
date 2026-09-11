"""
Lógica de negocio para los equipos.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from crud import equipment as crud_equipment
from crud import equipment_taxonomy as crud_taxonomy
from schemas.equipment import EquipmentCreate, EquipmentUpdate


async def create_equipment(db: AsyncSession, equipment_in: EquipmentCreate) -> dict:
    taxonomy = await crud_taxonomy.get_taxonomy_by_id(db, equipment_in.taxonomy_id)
    if not taxonomy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La taxonomía indicada no existe.",
        )

    existing = await crud_equipment.get_equipment_by_tag_number(db, equipment_in.tag_number)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El número de tag ya se encuentra registrado.",
        )

    payload = equipment_in.model_dump(exclude_unset=True)
    return await crud_equipment.create_equipment(db, payload)


async def get_equipment_or_404(db: AsyncSession, equipment_id: uuid.UUID):
    equipment = await crud_equipment.get_equipment_by_id(db, equipment_id)
    if not equipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Equipo no encontrado.",
        )
    return equipment


async def list_equipments(db: AsyncSession, skip: int = 0, limit: int = 100):
    return await crud_equipment.get_equipments(db=db, skip=skip, limit=limit)


async def update_equipment(db: AsyncSession, equipment_id: uuid.UUID, equipment_in: EquipmentUpdate):
    equipment = await get_equipment_or_404(db, equipment_id)
    update_data = equipment_in.model_dump(exclude_unset=True)

    if "taxonomy_id" in update_data and update_data["taxonomy_id"]:
        taxonomy = await crud_taxonomy.get_taxonomy_by_id(db, update_data["taxonomy_id"])
        if not taxonomy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La taxonomía indicada no existe.",
            )

    if "tag_number" in update_data and update_data["tag_number"]:
        existing = await crud_equipment.get_equipment_by_tag_number(db, update_data["tag_number"])
        if existing and existing.id != equipment_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El número de tag ya se encuentra asignado a otro equipo.",
            )

    return await crud_equipment.update_equipment(db, equipment, update_data)


async def deactivate_equipment(db: AsyncSession, equipment_id: uuid.UUID):
    equipment = await get_equipment_or_404(db, equipment_id)
    return await crud_equipment.deactivate_equipment(db, equipment)
