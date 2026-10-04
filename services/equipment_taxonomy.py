"""
Lógica de negocio para la taxonomía de equipos.
"""

import uuid
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from crud import equipment_taxonomy as crud_taxonomy
from schemas.equipment_taxonomy import EquipmentTaxonomyCreate, EquipmentTaxonomyUpdate

async def create_taxonomy(db: AsyncSession, taxonomy_in: EquipmentTaxonomyCreate, user_id: uuid.UUID) -> dict:
    """
    Crea un nodo de la jerarquía de activos.
    Cuando se informa parent_id, valida que la categoría padre exista
    antes de guardar la nueva taxonomía. Inyecta el ID del usuario creador.
    """
    payload = taxonomy_in.model_dump(exclude_unset=True)
    payload["created_by"] = user_id
    
    if payload.get("parent_id"):
        parent = await crud_taxonomy.get_taxonomy_by_id(db, payload["parent_id"])
        if not parent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La categoría padre indicada no existe.")
            
    return await crud_taxonomy.create_taxonomy(db, payload)

async def get_taxonomy_or_404(db: AsyncSession, taxonomy_id: uuid.UUID):
    """Obtiene una taxonomía por UUID o devuelve un error HTTP 404."""
    taxonomy = await crud_taxonomy.get_taxonomy_by_id(db, taxonomy_id)
    if not taxonomy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Taxonomía no encontrada.")
    return taxonomy

async def list_taxonomies(db: AsyncSession, skip: int = 0, limit: int = 100):
    """Devuelve una lista paginada de categorías de la taxonomía."""
    return await crud_taxonomy.get_taxonomies(db=db, skip=skip, limit=limit)

async def update_taxonomy(db: AsyncSession, taxonomy_id: uuid.UUID, taxonomy_in: EquipmentTaxonomyUpdate):
    """
    Actualiza parcialmente una categoría de equipos.
    Valida la nueva categoría padre cuando el cliente solicita
    mover el nodo dentro de la jerarquía.
    """
    taxonomy = await get_taxonomy_or_404(db, taxonomy_id)
    update_data = taxonomy_in.model_dump(exclude_unset=True)

    if update_data.get("parent_id"):
        if update_data["parent_id"] == taxonomy_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Un nodo de taxonomía no puede ser padre de sí mismo.")
            
        parent = await crud_taxonomy.get_taxonomy_by_id(db, update_data["parent_id"])
        if not parent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La categoría padre indicada no existe.")

    return await crud_taxonomy.update_taxonomy(db, taxonomy, update_data)

async def delete_taxonomy(db: AsyncSession, taxonomy_id: uuid.UUID):
    """Elimina una taxonomía solo si ninguna fila depende de ella."""
    taxonomy = await get_taxonomy_or_404(db, taxonomy_id)
    if await crud_taxonomy.has_children(db, taxonomy_id) or await crud_taxonomy.has_equipments(db, taxonomy_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede eliminar la taxonomía porque tiene equipos o subcategorías asociadas."
        )
    await crud_taxonomy.delete_taxonomy(db, taxonomy)