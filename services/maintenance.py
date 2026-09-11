"""
Lógica de negocio para los mantenimientos.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from crud import equipment as crud_equipment
from crud import maintenance as crud_maintenance
from schemas.maintenance import MaintenanceCreate, MaintenanceUpdate


async def create_maintenance(db: AsyncSession, maintenance_in: MaintenanceCreate):
    equipment = await crud_equipment.get_equipment_by_id(db, maintenance_in.equipment_id)
    if not equipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El equipo asociado al mantenimiento no existe.",
        )

    payload = maintenance_in.model_dump(exclude_unset=True)
    return await crud_maintenance.create_maintenance(db, payload)


async def get_maintenance_or_404(db: AsyncSession, maintenance_id: uuid.UUID):
    maintenance = await crud_maintenance.get_maintenance_by_id(db, maintenance_id)
    if not maintenance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mantenimiento no encontrado.",
        )
    return maintenance


async def list_maintenances(db: AsyncSession, skip: int = 0, limit: int = 100):
    return await crud_maintenance.get_maintenances(db=db, skip=skip, limit=limit)


async def update_maintenance(db: AsyncSession, maintenance_id: uuid.UUID, maintenance_in: MaintenanceUpdate):
    maintenance = await get_maintenance_or_404(db, maintenance_id)
    update_data = maintenance_in.model_dump(exclude_unset=True)

    if "equipment_id" in update_data and update_data["equipment_id"]:
        equipment = await crud_equipment.get_equipment_by_id(db, update_data["equipment_id"])
        if not equipment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El equipo asociado no existe.",
            )

    return await crud_maintenance.update_maintenance(db, maintenance, update_data)


async def deactivate_maintenance(db: AsyncSession, maintenance_id: uuid.UUID):
    maintenance = await get_maintenance_or_404(db, maintenance_id)
    return await crud_maintenance.deactivate_maintenance(db, maintenance)
