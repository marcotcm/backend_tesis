"""
Endpoints REST para la gestión del Almacén MRO (Repuestos Industriales).
"""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from db.session import get_db
from models.user import User
from schemas.spare_part import (
    SparePartCreate,
    SparePartResponse,
    SparePartStockAdjust,
    SparePartUpdate,
    SparePartsSummary,
)
from services import spare_parts as sp_service

router = APIRouter()


@router.get("/", response_model=List[SparePartResponse], status_code=status.HTTP_200_OK)
async def listar_repuestos(
    search: Optional[str] = Query(None, description="Buscar por SKU, nombre, proveedor o ubicación"),
    category: Optional[str] = Query(None, description="Filtrar por categoría"),
    low_stock_only: bool = Query(False, description="Mostrar solo repuestos en nivel bajo/crítico"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await sp_service.list_spare_parts(
        db=db,
        search=search,
        category=category,
        low_stock_only=low_stock_only,
        skip=skip,
        limit=limit,
    )


@router.get("/resumen", response_model=SparePartsSummary, status_code=status.HTTP_200_OK)
async def resumen_almacen_mro(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await sp_service.get_spare_parts_summary(db=db)


@router.post("/", response_model=SparePartResponse, status_code=status.HTTP_201_CREATED)
async def crear_repuesto(
    part_in: SparePartCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await sp_service.create_spare_part(db=db, part_in=part_in, current_user=current_user)


@router.put("/{part_id}", response_model=SparePartResponse, status_code=status.HTTP_200_OK)
async def actualizar_repuesto(
    part_id: uuid.UUID,
    part_in: SparePartUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await sp_service.update_spare_part(db=db, part_id=part_id, part_in=part_in)


@router.patch("/{part_id}/stock", response_model=SparePartResponse, status_code=status.HTTP_200_OK)
async def ajustar_stock_repuesto(
    part_id: uuid.UUID,
    adjust_in: SparePartStockAdjust,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await sp_service.adjust_spare_part_stock(
        db=db, part_id=part_id, adjust_in=adjust_in, current_user=current_user
    )


@router.delete("/{part_id}", status_code=status.HTTP_200_OK)
async def desactivar_repuesto(
    part_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await sp_service.deactivate_spare_part(db=db, part_id=part_id)
