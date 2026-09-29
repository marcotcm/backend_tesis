"""
Capa de Servicios y Reglas de Negocio para Métricas de Equipos.

Garantiza la inyección del usuario en sesión, protege la integridad de los 
datos históricos y centraliza la lógica de negocio para las consultas.
"""

import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from crud import equipment_metrics as crud_metrics
from schemas.equipment_metrics import EquipmentMetricCreate, EquipmentMetricUpdate
from models.equipment_metrics import EquipmentMetricHistory
from models.user import User, UserRole

async def record_metric(db: AsyncSession, metric_in: EquipmentMetricCreate, current_user: User) -> EquipmentMetricHistory:
    """Registra una nueva lectura vinculándola criptográficamente al usuario en sesión."""
    metric_data = metric_in.model_dump()
    metric_data["recorded_by"] = current_user.id
    
    try:
        return await crud_metrics.create_metric(db, obj_in=metric_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fallo al registrar la métrica en la base de datos: {str(e)}"
        )

# ==========================================
# NUEVAS FUNCIONES DE SERVICIO PARA LECTURA
# ==========================================
async def get_all_metrics(db: AsyncSession, skip: int, limit: int) -> List[EquipmentMetricHistory]:
    """Servicio para obtener el historial global."""
    return await crud_metrics.get_metrics(db, skip=skip, limit=limit)

async def get_equipment_metrics(db: AsyncSession, equipment_id: uuid.UUID, skip: int, limit: int) -> List[EquipmentMetricHistory]:
    """Servicio para obtener la tendencia de un equipo."""
    return await crud_metrics.get_metrics_by_equipment(db, equipment_id=equipment_id, skip=skip, limit=limit)

async def get_user_metrics(db: AsyncSession, user_id: uuid.UUID, skip: int, limit: int) -> List[EquipmentMetricHistory]:
    """Servicio para obtener las lecturas registradas por un técnico."""
    return await crud_metrics.get_metrics_by_user(db, user_id=user_id, skip=skip, limit=limit)

async def get_metrics_by_dates(
    db: AsyncSession, start_date: datetime, end_date: datetime, equipment_id: Optional[uuid.UUID], skip: int, limit: int
) -> List[EquipmentMetricHistory]:
    """Servicio para filtrar métricas por fechas con validación de negocio."""
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Error de negocio: La fecha de inicio no puede ser posterior a la fecha de fin."
        )
    return await crud_metrics.get_metrics_by_date_range(db, start_date, end_date, equipment_id, skip, limit)
# ==========================================

async def get_metric_or_404(db: AsyncSession, metric_id: uuid.UUID) -> EquipmentMetricHistory:
    """Obtiene una lectura o genera un error 404 estructurado."""
    metric = await crud_metrics.get_metric_by_id(db, metric_id)
    if not metric:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro de métrica no encontrado.")
    return metric

async def update_metric_record(
    db: AsyncSession, metric_id: uuid.UUID, metric_in: EquipmentMetricUpdate, current_user: User
) -> EquipmentMetricHistory:
    """Aplica una actualización restringida a una métrica existente."""
    db_metric = await get_metric_or_404(db, metric_id)
    
    if current_user.role != UserRole.admin and db_metric.recorded_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para modificar una métrica registrada por otro técnico."
        )
        
    update_data = metric_in.model_dump(exclude_unset=True)
    if not update_data:
        return db_metric
        
    return await crud_metrics.update_metric(db, db_obj=db_metric, update_data=update_data)

async def delete_metric_record(db: AsyncSession, metric_id: uuid.UUID, current_user: User) -> dict:
    """Elimina físicamente una lectura errónea. Restringido exclusivamente a administradores."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los administradores pueden eliminar registros históricos del sistema."
        )
        
    db_metric = await get_metric_or_404(db, metric_id)
    await crud_metrics.delete_metric(db, db_obj=db_metric)
    
    return {"detail": "Registro histórico de métrica eliminado permanentemente."}