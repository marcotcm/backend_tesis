"""
Esquemas Pydantic para los activos/equipos.
"""

import uuid
from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

EQUIPMENT_BULK_COLUMNS = (
    "taxonomy_id",
    "tag_number",
    "name",
    "equipment_type",
    "operational_status",
    "brand",
    "model",
    "function_description",
    "technical_specifications",
)


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
    usage_time: Optional[int] = None
    is_active: Optional[bool] = None

class UsageTimeUpdate(BaseModel):
    """Esquema específico para modificar los minutos de uso."""
    operation: Literal["add", "subtract", "set"]
    minutes: int = Field(..., ge=0, description="Cantidad de minutos a sumar, restar o establecer")

class EquipmentResponse(EquipmentBase):
    id: uuid.UUID
    usage_time: Optional[int] = None
    created_by: uuid.UUID
    updated_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EquipmentBulkError(BaseModel):
    row: int
    tag_number: Optional[str] = None
    error: str


class EquipmentBulkImportResponse(BaseModel):
    total_records: int
    successful_count: int
    failed_count: int
    created_ids: list[uuid.UUID]
    errors: list[EquipmentBulkError]