"""
Esquemas Pydantic para los mantenimientos.
"""

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class MaintenanceBase(BaseModel):
    equipment_id: uuid.UUID
    title: str
    maintenance_type: Literal["Preventivo", "Predictivo", "Correctivo", "Adaptativo (IA)"]
    description: Optional[str] = None
    frequency_days: Optional[int] = None
    is_active: bool = True
    created_by: uuid.UUID


class MaintenanceCreate(MaintenanceBase):
    pass


class MaintenanceUpdate(BaseModel):
    equipment_id: Optional[uuid.UUID] = None
    title: Optional[str] = None
    maintenance_type: Optional[Literal["Preventivo", "Predictivo", "Correctivo", "Adaptativo (IA)"]] = None
    description: Optional[str] = None
    frequency_days: Optional[int] = None
    is_active: Optional[bool] = None
    created_by: Optional[uuid.UUID] = None


class MaintenanceResponse(MaintenanceBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
