"""
Endpoints para la gestión de mantenimientos.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from schemas.maintenance import MaintenanceCreate, MaintenanceResponse, MaintenanceUpdate
from services import maintenance as maintenance_service

router = APIRouter()


@router.post(
    "/",
    response_model=MaintenanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_mantenimiento(
    maintenance_in: MaintenanceCreate,
    db: AsyncSession = Depends(get_db),
):
    return await maintenance_service.create_maintenance(db=db, maintenance_in=maintenance_in)


@router.get(
    "/",
    response_model=List[MaintenanceResponse],
    status_code=status.HTTP_200_OK,
)
async def listar_mantenimientos(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    equipment_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if equipment_id is not None:
        from crud import maintenance as crud_maintenance
        return await crud_maintenance.get_maintenances_by_equipment(db=db, equipment_id=equipment_id)
    return await maintenance_service.list_maintenances(db=db, skip=skip, limit=limit)


@router.get(
    "/{id}",
    response_model=MaintenanceResponse,
    status_code=status.HTTP_200_OK,
)
async def obtener_mantenimiento(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    return await maintenance_service.get_maintenance_or_404(db=db, maintenance_id=id)


@router.patch(
    "/{id}",
    response_model=MaintenanceResponse,
    status_code=status.HTTP_200_OK,
)
async def actualizar_mantenimiento(
    id: uuid.UUID,
    maintenance_in: MaintenanceUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await maintenance_service.update_maintenance(db=db, maintenance_id=id, maintenance_in=maintenance_in)


@router.delete(
    "/{id}",
    response_model=MaintenanceResponse,
    status_code=status.HTTP_200_OK,
)
async def desactivar_mantenimiento(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    return await maintenance_service.deactivate_maintenance(db=db, maintenance_id=id)
