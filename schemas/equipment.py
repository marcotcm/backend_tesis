"""
Esquemas Pydantic para los activos/equipos.
"""

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


class EquipmentBase(BaseModel):
    taxonomy_id: uuid.UUID
    tag_number: str
    name: str
    brand: Optional[str] = None
    model: Optional[str] = None
    equipment_type: Literal["Estatico", "Rotativo", "Electrico", "Instrumentacion"]
    operational_status: Literal["operational", "standby", "under_maintenance", "failed"] = "operational"
    technical_specifications: Optional[dict[str, Any]] = None
    function_description: Optional[str] = None
    is_active: bool = True
    created_by: uuid.UUID
    updated_by: Optional[uuid.UUID] = None


class EquipmentCreate(EquipmentBase):
    pass


class EquipmentUpdate(BaseModel):
    taxonomy_id: Optional[uuid.UUID] = None
    tag_number: Optional[str] = None
    name: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    equipment_type: Optional[Literal["Estatico", "Rotativo", "Electrico", "Instrumentacion"]] = None
    operational_status: Optional[Literal["operational", "standby", "under_maintenance", "failed"]] = None
    technical_specifications: Optional[dict[str, Any]] = None
    function_description: Optional[str] = None
    is_active: Optional[bool] = None
    updated_by: Optional[uuid.UUID] = None


class EquipmentResponse(EquipmentBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
