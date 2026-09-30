import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AICorrectionCreate(BaseModel):
    recommendation_id: uuid.UUID
    corrected_text: str = Field(min_length=1)

class AICorrectionUpdate(BaseModel):
    corrected_text: str = Field(min_length=1)


class AICorrectionResponse(AICorrectionCreate):
    id: uuid.UUID
    corrected_by: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True
