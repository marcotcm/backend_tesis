import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

RecommendationStatus = Literal["Pendiente", "Aceptada", "Rechazada"]


class AIRecommendationCreate(BaseModel):
    equipment_id: uuid.UUID
    trigger_source: str
    trigger_reference_id: Optional[uuid.UUID] = None
    recommendation_text: str
    confidence_score: float = Field(ge=0, le=100)
    prediction_type: str


class AIRecommendationUpdate(BaseModel):
    trigger_source: Optional[str] = None
    trigger_reference_id: Optional[uuid.UUID] = None
    recommendation_text: Optional[str] = None
    confidence_score: Optional[float] = Field(None, ge=0, le=100)
    prediction_type: Optional[str] = None


class AIRecommendationStatusUpdate(BaseModel):
    status: RecommendationStatus


class AIRecommendationResponse(AIRecommendationCreate):
    id: uuid.UUID
    status: RecommendationStatus
    created_at: datetime
    resolved_by: Optional[uuid.UUID] = None
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True
