"""
Endpoints REST para Consola de Alarmas Industriales ISA-18.2.
"""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from db.session import get_db
from models.user import User
from schemas.industrial_alarm import (
    AlarmAckRequest,
    AlarmShelveRequest,
    AlarmsSummary,
    IndustrialAlarmResponse,
)
from services import industrial_alarms as alarm_service

router = APIRouter()


@router.get("/", response_model=List[IndustrialAlarmResponse], status_code=status.HTTP_200_OK)
async def listar_alarmas_isa18(
    state: Optional[str] = Query(None, description="Filtrar por estado ISA-18.2"),
    priority: Optional[str] = Query(None, description="Filtrar por prioridad (P1_CRITICAL..P4_LOW)"),
    equipment_id: Optional[uuid.UUID] = Query(None, description="Filtrar por equipo"),
    include_cleared: bool = Query(False, description="Incluir alarmas CLEARED_ACK históricas"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await alarm_service.list_alarms(
        db=db,
        state=state,
        priority=priority,
        equipment_id=equipment_id,
        include_cleared=include_cleared,
        skip=skip,
        limit=limit,
    )


@router.get("/resumen", response_model=AlarmsSummary, status_code=status.HTTP_200_OK)
async def resumen_alarmas_isa18(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await alarm_service.get_alarms_summary(db=db)


@router.post("/{alarm_id}/ack", response_model=IndustrialAlarmResponse, status_code=status.HTTP_200_OK)
async def reconocer_alarma(
    alarm_id: uuid.UUID,
    payload: AlarmAckRequest = AlarmAckRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await alarm_service.acknowledge_alarm(
        db=db, alarm_id=alarm_id, ack_req=payload, current_user=current_user
    )


@router.post("/{alarm_id}/shelve", response_model=IndustrialAlarmResponse, status_code=status.HTTP_200_OK)
async def silenciar_alarma(
    alarm_id: uuid.UUID,
    payload: AlarmShelveRequest = AlarmShelveRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await alarm_service.shelve_alarm(
        db=db, alarm_id=alarm_id, shelve_req=payload, current_user=current_user
    )
