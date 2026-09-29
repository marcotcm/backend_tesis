import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class EquipmentCriticalityCreate(BaseModel):
    equipment_id: uuid.UUID
    safety_impact_score: int = Field(ge=0, le=100)
    environmental_impact_score: int = Field(ge=0, le=100)
    operational_impact_score: int = Field(ge=0, le=100)
    maintenance_cost_score: int = Field(ge=0, le=100)
    rpn_score: int = Field(ge=0, le=100)
    criticality_level: Literal["Alta", "Media", "Baja"]


class EquipmentCriticalityUpdate(BaseModel):
    safety_impact_score: Optional[int] = Field(None, ge=0, le=100)
    environmental_impact_score: Optional[int] = Field(None, ge=0, le=100)
    operational_impact_score: Optional[int] = Field(None, ge=0, le=100)
    maintenance_cost_score: Optional[int] = Field(None, ge=0, le=100)
    rpn_score: Optional[int] = Field(None, ge=0, le=100)
    criticality_level: Optional[Literal["Alta", "Media", "Baja"]] = None


class EquipmentCriticalityResponse(EquipmentCriticalityCreate):
    id: uuid.UUID
    evaluated_by: uuid.UUID
    evaluated_at: datetime

    class Config:
        from_attributes = True
