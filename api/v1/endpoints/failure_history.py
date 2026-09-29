"""
Rutas y Controladores de la API para el Módulo de Historial de Fallas (Sistema RCM).

Define los endpoints RESTful protegidos y documentados para Swagger/OpenAPI,
gestionando el registro y análisis de paradas no programadas en equipos.
"""

import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from core.security import get_current_user, RoleChecker
from models.user import User, UserRole
from schemas.failure_history import FailureHistoryCreate, FailureHistoryUpdate, FailureHistoryResponse
from services import failure_history as failure_service

router = APIRouter()

@router.post("/", response_model=FailureHistoryResponse, status_code=status.HTTP_201_CREATED)
async def reportar_falla(
    failure_in: FailureHistoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** POST /api/v1/fallas/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Levanta un reporte oficial detallando el modo de falla, severidad y tiempo de inactividad de un equipo.
    * **Resultado:** Persiste la avería en el sistema marcando al usuario activo como informante, previniendo errores de fecha en el futuro.
    """
    return await failure_service.report_failure(db=db, failure_in=failure_in, current_user=current_user)

@router.get("/", response_model=List[FailureHistoryResponse], status_code=status.HTTP_200_OK)
async def listar_fallas_globales(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/fallas/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Obtiene el libro maestro consolidado de todos los incidentes ocurridos en la planta operativa.
    * **Resultado:** Retorna un arreglo JSON paginado ordenando las averías de la más reciente a la más antigua.
    """
    return await failure_service.get_all_failures(db=db, skip=skip, limit=limit)

@router.get("/equipo/{equipment_id}", response_model=List[FailureHistoryResponse], status_code=status.HTTP_200_OK)
async def historial_de_fallas_por_equipo(
    equipment_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/fallas/equipo/{equipment_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Extrae el expediente de averías y paradas de una máquina específica para cálculos de confiabilidad (MTBF).
    * **Resultado:** Entrega la secuencia de fallos asociados al equipo consultado.
    """
    return await failure_service.get_equipment_failures(db=db, equipment_id=equipment_id, skip=skip, limit=limit)

@router.get("/reportado-por/{user_id}", response_model=List[FailureHistoryResponse], status_code=status.HTTP_200_OK)
async def fallas_reportadas_por_usuario(
    user_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/fallas/reportado-por/{user_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Revisa todos los reportes de incidentes levantados en campo por un técnico o ingeniero determinado.
    * **Resultado:** Emite la lista de fallas vinculadas a la firma electrónica de ese trabajador en particular.
    """
    return await failure_service.get_reporter_failures(db=db, user_id=user_id, skip=skip, limit=limit)

@router.get("/buscar/fecha", response_model=List[FailureHistoryResponse], status_code=status.HTTP_200_OK)
async def buscar_fallas_por_fecha(
    fecha_inicio: datetime = Query(..., description="Fecha de inicio (ISO 8601)"),
    fecha_fin: datetime = Query(..., description="Fecha de fin (ISO 8601)"),
    equipo_id: Optional[uuid.UUID] = Query(None, description="UUID del equipo (Opcional)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/fallas/buscar/fecha
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Aísla temporalmente un grupo de averías para identificar clusters o hacer cortes de gestión gerencial.
    * **Resultado:** Proporciona los eventos críticos ocurridos entre las fechas estipuladas, con soporte opcional de un equipo puntual.
    """
    return await failure_service.get_failures_by_dates(
        db=db, start_date=fecha_inicio, end_date=fecha_fin, equipment_id=equipo_id, skip=skip, limit=limit
    )

@router.get("/{id}", response_model=FailureHistoryResponse, status_code=status.HTTP_200_OK)
async def obtener_falla_por_id(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/fallas/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Visualiza a detalle la bitácora, horas caídas y diagnóstico de un evento de falla específico.
    * **Resultado:** Devuelve todos los campos asociados al incidente, enlazando potencialmente con análisis AMFE.
    """
    return await failure_service.get_failure_or_404(db, id)

@router.patch("/{id}", response_model=FailureHistoryResponse, status_code=status.HTTP_200_OK)
async def actualizar_falla(
    id: uuid.UUID,
    failure_in: FailureHistoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** PATCH /api/v1/fallas/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Informante original, Administrador o Auditor Técnico
    * **Uso:** Ajusta métricas secundarias de la falla (como actualizar el downtime total tras reparar la máquina).
    * **Resultado:** Ejecuta el cambio controlado en la matriz asegurando el registro de auditoría vigente.
    """
    return await failure_service.update_failure_record(db=db, failure_id=id, failure_in=failure_in, current_user=current_user)

@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def purgar_falla(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.admin]))
):
    """
    * **Ruta:** DELETE /api/v1/fallas/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Exclusivo Administrador (`admin`)
    * **Uso:** Descarta administrativamente un reporte de rotura ingresado por error que contamina el inventario.
    * **Resultado:** Suprime permanentemente el suceso de las tablas (Hard Delete).
    """
    return await failure_service.delete_failure_record(db=db, failure_id=id, current_user=current_user)