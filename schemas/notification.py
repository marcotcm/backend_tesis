from pydantic import BaseModel, UUID4, ConfigDict
from typing import Optional
from datetime import datetime

class NotificationBase(BaseModel):
    title: str
    message: str
    notification_type: str

class NotificationCreate(NotificationBase):
    user_id: Optional[UUID4] = None

class NotificationResponse(NotificationBase):
    id: UUID4
    user_id: Optional[UUID4] = None
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)