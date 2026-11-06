import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class UserPushTokenCreate(BaseModel):
    token: str = Field(min_length=1)

    @field_validator("token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El token push no puede estar vacío.")
        return value


class UserPushTokenResponse(BaseModel):
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_seen_at: Optional[datetime] = None

    class Config:
        from_attributes = True
