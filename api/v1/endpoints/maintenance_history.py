"""
Rutas y Controladores de la API para el Historial de Mantenimientos (Sistema RCM).

Define los endpoints RESTful protegidos y documentados para Swagger/OpenAPI,
encargados de registrar las labores técnicas ejecutadas y su trazabilidad de componentes.
"""

import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from core.security import get_current_user, RoleChecker
from models.user import User, UserRole
from schemas.maintenance_history import MaintenanceHistoryCreate, MaintenanceHistoryUpdate, MaintenanceHistoryResponse
from services import maintenance_history as history_service

router = APIRouter()

@router.post("/", response_model=MaintenanceHistoryResponse, status_code=status.HTTP_201_CREATED)
async def registrar_ejecucion_mantenimiento(
    record_in: MaintenanceHistoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** POST /api/v1/historial-mantenimientos/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Archiva formalmente el descargo técnico de un mantenimiento realizado (horas invertidas, acciones, repuestos).
    * **Resultado:** Consolida la labor asociando el usuario activo como técnico ejecutor y cierra el ciclo de la orden de trabajo.
    """
    return await history_service.log_maintenance_execution(db=db, record_in=record_in, current_user=current_user)

@router.get("/", response_model=List[MaintenanceHistoryResponse], status_code=status.HTTP_200_OK)
async def listar_historial_global(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/historial-mantenimientos/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Accede a la bitácora integral de todas las intervenciones ejecutadas sobre los activos físicos de la planta.
    * **Resultado:** Devuelve una lista JSON cronológica con el registro inmutable de las reparaciones pasadas.
    """
    return await history_service.get_all_histories(db=db, skip=skip, limit=limit)

@router.get("/equipo/{equipment_id}", response_model=List[MaintenanceHistoryResponse], status_code=status.HTTP_200_OK)
async def historial_ejecuciones_por_equipo(
    equipment_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/historial-mantenimientos/equipo/{equipment_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Consulta el prontuario completo de vida de una máquina para calcular costos de repuestos y recurrencia de intervenciones.
    * **Resultado:** Retorna las labores técnicas efectuadas exclusivamente sobre el equipo especificado.
    """
    return await history_service.get_equipment_history(db=db, equipment_id=equipment_id, skip=skip, limit=limit)

@router.get("/tecnico/{user_id}", response_model=List[MaintenanceHistoryResponse], status_code=status.HTTP_200_OK)
async def historial_por_tecnico_ejecutor(
    user_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/historial-mantenimientos/tecnico/{user_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Analiza el desempeño y volumen de trabajo resuelto por un trabajador de campo (auditoría de HH invertidas).
    * **Resultado:** Emite los registros donde la firma electrónica coincida con el trabajador consultado.
    """
    return await history_service.get_executor_history(db=db, user_id=user_id, skip=skip, limit=limit)

@router.get("/orden-trabajo/{wo_id}", response_model=List[MaintenanceHistoryResponse], status_code=status.HTTP_200_OK)
async def resolucion_de_orden(
    wo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/historial-mantenimientos/orden-trabajo/{wo_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Cruza una orden de trabajo con su evidencia técnica de cierre y partes consumidas en bodega.
    * **Resultado:** Retorna el descargo o los descargos asociados a un ticket de planificación particular.
    """
    return await history_service.get_wo_history(db=db, wo_id=wo_id)

@router.get("/falla/{failure_id}", response_model=List[MaintenanceHistoryResponse], status_code=status.HTTP_200_OK)
async def solucion_de_falla(
    failure_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/historial-mantenimientos/falla/{failure_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Investiga cuál fue el correctivo mecánico o eléctrico aplicado a raíz de una rotura reportada.
    * **Resultado:** Extrae los historiales marcados como generados por la avería ('was_failure_driven' y 'failure_id').
    """
    return await history_service.get_failure_history_fixes(db=db, failure_id=failure_id)

@router.get("/buscar/fecha", response_model=List[MaintenanceHistoryResponse], status_code=status.HTTP_200_OK)
async def historiales_por_fecha(
    fecha_inicio: datetime = Query(..., description="Fecha de inicio (ISO 8601)"),
    fecha_fin: datetime = Query(..., description="Fecha de fin (ISO 8601)"),
    equipo_id: Optional[uuid.UUID] = Query(None, description="UUID del equipo (Opcional)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/historial-mantenimientos/buscar/fecha
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Mide la concentración de ejecuciones, consumo de partes o HH en periodos fiscales (mensual, trimestral).
    * **Resultado:** Lista los registros de mantenimiento limitados a la ventana cronológica especificada.
    """
    return await history_service.get_histories_by_date(
        db=db, start_date=fecha_inicio, end_date=fecha_fin, equipment_id=equipo_id, skip=skip, limit=limit
    )

@router.get("/{id}", response_model=MaintenanceHistoryResponse, status_code=status.HTTP_200_OK)
async def obtener_historial_por_id(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/historial-mantenimientos/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Pide el detalle completo de un acta de mantenimiento individual.
    * **Resultado:** Muestra notas, consumibles y tiempos asociados al acta. Lanza 404 si es inexistente.
    """
    return await history_service.get_history_or_404(db, id)

@router.patch("/{id}", response_model=MaintenanceHistoryResponse, status_code=status.HTTP_200_OK)
async def actualizar_historial(
    id: uuid.UUID,
    record_in: MaintenanceHistoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** PATCH /api/v1/historial-mantenimientos/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Ejecutor original, Auditor Técnico o Administrador
    * **Uso:** Añade o corrige anotaciones de campo olvidables post-cierre (ej. ajuste fino a las partes reemplazadas).
    * **Resultado:** Impacta los cambios menores de manera validada y auditable.
    """
    return await history_service.update_maintenance_record(db=db, record_id=id, record_in=record_in, current_user=current_user)

@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def purgar_historial(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.admin]))
):
    """
    * **Ruta:** DELETE /api/v1/historial-mantenimientos/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Exclusivo Administrador (`admin`)
    * **Uso:** Anula físicamente un registro histórico fraudulento o generado por pruebas de QA.
    * **Resultado:** Borrado definitivo de la tabla de descargas (Hard Delete).
    """
    return await history_service.delete_maintenance_record(db=db, record_id=id, current_user=current_user)