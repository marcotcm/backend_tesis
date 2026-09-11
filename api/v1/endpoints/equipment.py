"""
Endpoints para la gestión de equipos y activos.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from schemas.equipment import EquipmentCreate, EquipmentResponse, EquipmentUpdate
from services import equipment as equipment_service

router = APIRouter()


@router.post(
    "/",
    response_model=EquipmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_equipo(
    equipment_in: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
):
    return await equipment_service.create_equipment(db=db, equipment_in=equipment_in)


@router.get(
    "/",
    response_model=List[EquipmentResponse],
    status_code=status.HTTP_200_OK,
)
async def listar_equipos(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    taxonomy_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if taxonomy_id is not None:
        from crud import equipment as crud_equipment
        return await crud_equipment.get_equipments_by_taxonomy(db=db, taxonomy_id=taxonomy_id)
    return await equipment_service.list_equipments(db=db, skip=skip, limit=limit)


@router.get(
    "/{id}",
    response_model=EquipmentResponse,
    status_code=status.HTTP_200_OK,
)
async def obtener_equipo(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    return await equipment_service.get_equipment_or_404(db=db, equipment_id=id)


@router.patch(
    "/{id}",
    response_model=EquipmentResponse,
    status_code=status.HTTP_200_OK,
)
async def actualizar_equipo(
    id: uuid.UUID,
    equipment_in: EquipmentUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await equipment_service.update_equipment(db=db, equipment_id=id, equipment_in=equipment_in)


@router.delete(
    "/{id}",
    response_model=EquipmentResponse,
    status_code=status.HTTP_200_OK,
)
async def desactivar_equipo(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    return await equipment_service.deactivate_equipment(db=db, equipment_id=id)
