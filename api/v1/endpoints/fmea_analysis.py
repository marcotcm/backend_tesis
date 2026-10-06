import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from crud import fmea_analysis as crud
from db.session import get_db
from models.user import User
from schemas.fmea_analysis import FMEAAnalysisCreate, FMEAAnalysisResponse, FMEAAnalysisUpdate
from services import fmea_analysis as service

router = APIRouter()


@router.post(
    "/",
    response_model=FMEAAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear análisis FMEA",
    description="Registra un análisis FMEA para un equipo con severidad, ocurrencia y detección de 1 a 10.",
)
async def create_fmea(
    data: FMEAAnalysisCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.create(db, data, current_user)


@router.get(
    "/",
    response_model=list[FMEAAnalysisResponse],
    summary="Listar análisis FMEA",
    description="Obtiene los análisis FMEA registrados, con filtro opcional por equipo.",
)
async def list_fmea(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    equipment_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if equipment_id:
        return await crud.get_by_equipment(db, equipment_id)
    return await crud.list_all(db, skip, limit)


@router.get(
    "/{id}",
    response_model=FMEAAnalysisResponse,
    summary="Consultar análisis FMEA",
    description="Devuelve un análisis FMEA por identificador UUID.",
)
async def get_fmea(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get(db, id)


@router.patch(
    "/{id}",
    response_model=FMEAAnalysisResponse,
    summary="Actualizar análisis FMEA",
    description="Actualiza un análisis FMEA y recalcula el RPN.",
)
async def update_fmea(
    id: uuid.UUID,
    data: FMEAAnalysisUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.update(db, id, data, current_user)
