"""
Capa de Servicios y Reglas de Negocio para el Historial de Mantenimientos.
"""

import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from crud import maintenance_history as crud_history
from schemas.maintenance_history import MaintenanceHistoryCreate, MaintenanceHistoryUpdate
from models.maintenance_history import MaintenanceHistory
from models.user import User, UserRole

async def log_maintenance_execution(db: AsyncSession, record_in: MaintenanceHistoryCreate, current_user: User) -> MaintenanceHistory:
    record_data = record_in.model_dump()
    record_data["executed_by"] = current_user.id
    
    try:
        return await crud_history.create_record(db, obj_in=record_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fallo al registrar el historial de mantenimiento: {str(e)}"
        )

async def get_history_or_404(db: AsyncSession, record_id: uuid.UUID) -> MaintenanceHistory:
    record = await crud_history.get_record_by_id(db, record_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro histórico no encontrado.")
    return record

async def get_all_histories(db: AsyncSession, skip: int, limit: int) -> List[MaintenanceHistory]:
    return await crud_history.get_all_records(db, skip, limit)

async def get_equipment_history(db: AsyncSession, equipment_id: uuid.UUID, skip: int, limit: int) -> List[MaintenanceHistory]:
    return await crud_history.get_records_by_equipment(db, equipment_id, skip, limit)

async def get_executor_history(db: AsyncSession, user_id: uuid.UUID, skip: int, limit: int) -> List[MaintenanceHistory]:
    return await crud_history.get_records_by_executor(db, user_id, skip, limit)

async def get_wo_history(db: AsyncSession, wo_id: uuid.UUID) -> List[MaintenanceHistory]:
    return await crud_history.get_records_by_work_order(db, wo_id)

async def get_failure_history_fixes(db: AsyncSession, failure_id: uuid.UUID) -> List[MaintenanceHistory]:
    return await crud_history.get_records_by_failure(db, failure_id)

async def get_histories_by_date(
    db: AsyncSession, start_date: datetime, end_date: datetime, equipment_id: Optional[uuid.UUID], skip: int, limit: int
) -> List[MaintenanceHistory]:
    if start_date > end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La fecha inicial no puede superar a la final.")
    return await crud_history.get_records_by_dates(db, start_date, end_date, equipment_id, skip, limit)

async def update_maintenance_record(
    db: AsyncSession, record_id: uuid.UUID, record_in: MaintenanceHistoryUpdate, current_user: User
) -> MaintenanceHistory:
    db_record = await get_history_or_404(db, record_id)
    
    if current_user.role not in [UserRole.admin, UserRole.technical_auditor] and db_record.executed_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el técnico ejecutor o el auditor técnico pueden modificar este descargo."
        )
        
    update_data = record_in.model_dump(exclude_unset=True)
    if not update_data:
        return db_record
        
    return await crud_history.update_record(db, db_obj=db_record, update_data=update_data)

async def delete_maintenance_record(db: AsyncSession, record_id: uuid.UUID, current_user: User) -> dict:
    """Borrado físico administrativo. La tabla no posee columna de soft-delete, se restringe a Admins."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un administrador tiene privilegios para eliminar historiales de ejecución."
        )
        
    db_record = await get_history_or_404(db, record_id)
    await crud_history.delete_record(db, db_obj=db_record)
    return {"detail": "Historial de mantenimiento purgado exitosamente."}