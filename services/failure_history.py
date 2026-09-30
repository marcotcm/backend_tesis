"""
Capa de Servicios para Fallas.
Concentra reglas de negocio, autorizaciones y puente seguro hacia el CRUD.
"""

import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from crud import failure_history as crud_failure
from schemas.failure_history import FailureHistoryCreate, FailureHistoryUpdate
from models.failure_history import FailureHistory
from models.user import User, UserRole

async def report_failure(db: AsyncSession, failure_in: FailureHistoryCreate, current_user: User) -> FailureHistory:
    """Emite un reporte de avería asociando al usuario en sesión como el informante."""
    failure_data = failure_in.model_dump()
    failure_data["reported_by"] = current_user.id
    
    try:
        return await crud_failure.create_failure(db, obj_in=failure_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al registrar la avería: {str(e)}"
        )

async def get_all_failures(db: AsyncSession, skip: int, limit: int) -> List[FailureHistory]:
    """Obtiene todo el historial de fallas de la planta."""
    return await crud_failure.get_failures(db, skip=skip, limit=limit)

async def get_equipment_failures(db: AsyncSession, equipment_id: uuid.UUID, skip: int, limit: int) -> List[FailureHistory]:
    """Obtiene las fallas de una máquina para análisis MTBF."""
    return await crud_failure.get_failures_by_equipment(db, equipment_id=equipment_id, skip=skip, limit=limit)

async def get_reporter_failures(db: AsyncSession, user_id: uuid.UUID, skip: int, limit: int) -> List[FailureHistory]:
    """Obtiene los incidentes levantados por un trabajador."""
    return await crud_failure.get_failures_by_reporter(db, user_id=user_id, skip=skip, limit=limit)

async def get_failures_by_dates(
    db: AsyncSession, start_date: datetime, end_date: datetime, equipment_id: Optional[uuid.UUID], skip: int, limit: int
) -> List[FailureHistory]:
    """Consulta de eventos por periodo, previniendo rangos ilógicos."""
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Error de negocio: La fecha inicial no puede superar a la fecha final."
        )
    return await crud_failure.get_failures_by_date_range(db, start_date, end_date, equipment_id, skip, limit)

async def get_failure_or_404(db: AsyncSession, failure_id: uuid.UUID) -> FailureHistory:
    """Recupera un reporte o lanza 404 estructurado."""
    failure = await crud_failure.get_failure_by_id(db, failure_id)
    if not failure:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reporte de falla no encontrado.")
    return failure

async def update_failure_record(
    db: AsyncSession, failure_id: uuid.UUID, failure_in: FailureHistoryUpdate, current_user: User
) -> FailureHistory:
    """Actualiza datos post-evento (como ajustar las horas reales de inactividad)."""
    db_failure = await get_failure_or_404(db, failure_id)
    
    # Regla: Solo el que lo reportó o un admin/auditor pueden editar la falla
    if current_user.role not in [UserRole.admin, UserRole.technical_auditor] and db_failure.reported_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Privilegios insuficientes. Solo el informante original o el auditor técnico pueden modificar este reporte."
        )
        
    update_data = failure_in.model_dump(exclude_unset=True)
    if not update_data:
        return db_failure
        
    return await crud_failure.update_failure(db, db_obj=db_failure, update_data=update_data)

async def delete_failure_record(db: AsyncSession, failure_id: uuid.UUID, current_user: User) -> dict:
    """Borrado de reporte. Exclusivo para administradores."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un administrador puede borrar el historial de paradas de la planta."
        )
        
    db_failure = await get_failure_or_404(db, failure_id)
    await crud_failure.delete_failure(db, db_obj=db_failure)
    
    return {"detail": "El reporte de falla fue purgado exitosamente."}