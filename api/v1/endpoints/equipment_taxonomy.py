"""
Endpoints para la taxonomía de equipos.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from crud import equipment_taxonomy as crud_taxonomy
from db.session import get_db
from core.security import get_current_user
from models.user import User
from schemas.equipment_taxonomy import (
    EquipmentTaxonomyCreate,
    EquipmentTaxonomyResponse,
    EquipmentTaxonomyUpdate,
)
from services import equipment_taxonomy as taxonomy_service

router = APIRouter()

@router.post(
    "/",
    response_model=EquipmentTaxonomyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear categoría de taxonomía",
)
async def crear_taxonomia(
    taxonomy_in: EquipmentTaxonomyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** POST /api/v1/taxonomia/
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
    * **Uso:** Crea una categoría dentro de la jerarquía planta, sistema,
      subsistema o componente.
    * **Resultado:** Registra la categoría y valida que la categoría padre
      exista cuando se proporciona `parent_id`.
    """
    return await taxonomy_service.create_taxonomy(db=db, taxonomy_in=taxonomy_in, user_id=current_user.id)


@router.get(
    "/",
    response_model=List[EquipmentTaxonomyResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar categorías de taxonomía",
)
async def listar_taxonomias(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** GET /api/v1/taxonomia/
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
    * **Uso:** Consulta las categorías de la jerarquía de activos con paginación.
    * **Resultado:** Retorna una lista de categorías ordenadas por nivel.
    """
    return await taxonomy_service.list_taxonomies(db=db, skip=skip, limit=limit)


@router.get(
    "/{id}",
    response_model=EquipmentTaxonomyResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar categoría de taxonomía",
)
async def obtener_taxonomia(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** GET /api/v1/taxonomia/{id}
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
    * **Uso:** Consulta una categoría mediante su UUID.
    * **Resultado:** Retorna la categoría solicitada o un error 404 si no existe.
    """
    return await taxonomy_service.get_taxonomy_or_404(db=db, taxonomy_id=id)


@router.patch(
    "/{id}",
    response_model=EquipmentTaxonomyResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar categoría de taxonomía",
)
async def actualizar_taxonomia(
    id: uuid.UUID,
    taxonomy_in: EquipmentTaxonomyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** PATCH /api/v1/taxonomia/{id}
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
    * **Uso:** Actualiza parcialmente el nombre, nivel, descripción o categoría padre.
    * **Resultado:** Retorna la categoría actualizada.
    """
    return await taxonomy_service.update_taxonomy(db=db, taxonomy_id=id, taxonomy_in=taxonomy_in)


@router.delete(
    "/{id}",
    response_model=EquipmentTaxonomyResponse,
    status_code=status.HTTP_200_OK,
    summary="Eliminar categoría de taxonomía",
)
async def eliminar_taxonomia(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** DELETE /api/v1/taxonomia/{id}
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
    * **Uso:** Elimina una categoría únicamente cuando no tiene equipos ni subcategorías asociadas.
    * **Resultado:** Aplica baja lógica al registro marcando `deleted_at`.
    """
    return await taxonomy_service.delete_taxonomy(db=db, taxonomy_id=id)