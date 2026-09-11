import uuid
from typing import List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from core.security import get_current_user, RoleChecker
from models.user import User, UserRole
from schemas.equipment_metric import EquipmentMetricCreate, EquipmentMetricResponse
from services import equipment_metric as metric_service

router = APIRouter()

@router.post("/", response_model=EquipmentMetricResponse, status_code=status.HTTP_201_CREATED)
async def registrar_lectura_equipo(
    metric_in: EquipmentMetricCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** POST /api/v1/metricas/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol Operativo)
    * **Uso:** Recibe las variables físicas (Temperatura, Vibración, Horas, etc.) medidas en campo o vía IoT para un equipo.
    * **Resultado:** Registra un nuevo hito histórico inmutable. El sistema asocia automáticamente el 'recorded_by' y 'recorded_at' basándose en el JWT y el servidor.
    """
    return await metric_service.register_metric(db=db, metric_in=metric_in, current_user=current_user)


@router.get("/equipo/{equipment_id}", response_model=List[EquipmentMetricResponse], status_code=status.HTTP_200_OK)
async def consultar_historial_equipo(
    equipment_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="Registros a omitir"),
    limit: int = Query(100, ge=1, le=500, description="Límite máximo de lecturas"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/metricas/equipo/{equipment_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Consulta el comportamiento histórico de las variables físicas de un activo industrial.
    * **Resultado:** Retorna un arreglo JSON paginado con las lecturas ordenadas desde la más reciente hasta la más antigua, vital para generar gráficas de tendencia o predicciones de IA.
    """
    return await metric_service.get_equipment_history(db=db, equipment_id=equipment_id, skip=skip, limit=limit)