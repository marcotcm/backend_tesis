import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


FMEAStatus = Literal["PENDIENTE", "EN ANÁLISIS", "CERRADO"]


class FMEAAnalysisCreate(BaseModel):
    equipment_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=200)
    status: FMEAStatus = "PENDIENTE"
    severity: int = Field(ge=1, le=10)
    occurrence: int = Field(ge=1, le=10)
    detection: int = Field(ge=1, le=10)
    description: str = Field(..., min_length=1)
    causes: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    current_controls: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class FMEAAnalysisUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    status: Optional[FMEAStatus] = None
    severity: Optional[int] = Field(None, ge=1, le=10)
    occurrence: Optional[int] = Field(None, ge=1, le=10)
    detection: Optional[int] = Field(None, ge=1, le=10)
    description: Optional[str] = Field(None, min_length=1)
    causes: Optional[list[str]] = None
    effects: Optional[list[str]] = None
    current_controls: Optional[list[str]] = None
    recommended_actions: Optional[list[str]] = None


class FMEAAnalysisResponse(FMEAAnalysisCreate):
    id: uuid.UUID
    rpn_score: int
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
