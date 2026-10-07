from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from db.session import get_db
from schemas.dashboard import DashboardSummary
from services import dashboard as service

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get(
    "/resumen",
    response_model=DashboardSummary,
    summary="Consultar resumen del dashboard",
    description=(
        "Devuelve conteos agregados de equipos, órdenes de trabajo y fallas, "
        "además de actividad reciente. No incluye el diagnóstico de salud "
        "operativa de planta."
    ),
)
async def get_dashboard_summary(
    activity_limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_summary(db, activity_limit)
