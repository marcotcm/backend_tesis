"""
Lógica de negocio para la taxonomía de equipos.
"""

import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from crud import equipment_taxonomy as crud_taxonomy
from schemas.equipment_taxonomy import EquipmentTaxonomyCreate, EquipmentTaxonomyUpdate


async def create_taxonomy(db: AsyncSession, taxonomy_in: EquipmentTaxonomyCreate) -> dict:
    payload = taxonomy_in.model_dump(exclude_unset=True)
    if payload.get("parent_id"):
        parent = await crud_taxonomy.get_taxonomy_by_id(db, payload["parent_id"])
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La categoría padre indicada no existe.",
            )

    taxonomy = await crud_taxonomy.create_taxonomy(db, payload)
    return taxonomy


async def get_taxonomy_or_404(db: AsyncSession, taxonomy_id: uuid.UUID):
    taxonomy = await crud_taxonomy.get_taxonomy_by_id(db, taxonomy_id)
    if not taxonomy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Taxonomía no encontrada.",
        )
    return taxonomy


async def list_taxonomies(db: AsyncSession, skip: int = 0, limit: int = 100):
    return await crud_taxonomy.get_taxonomies(db=db, skip=skip, limit=limit)


async def update_taxonomy(
    db: AsyncSession,
    taxonomy_id: uuid.UUID,
    taxonomy_in: EquipmentTaxonomyUpdate,
):
    taxonomy = await get_taxonomy_or_404(db, taxonomy_id)
    update_data = taxonomy_in.model_dump(exclude_unset=True)

    if "parent_id" in update_data and update_data["parent_id"]:
        parent = await crud_taxonomy.get_taxonomy_by_id(db, update_data["parent_id"])
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La categoría padre indicada no existe.",
            )

    return await crud_taxonomy.update_taxonomy(db, taxonomy, update_data)


async def delete_taxonomy(db: AsyncSession, taxonomy_id: uuid.UUID):
    taxonomy = await get_taxonomy_or_404(db, taxonomy_id)
    await crud_taxonomy.delete_taxonomy(db, taxonomy)
    return {"detail": "Taxonomía eliminada correctamente."}
