from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, date
import uuid
from models.user import user_role, turn 

class UserBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    identification_id: str
    birth_date: Optional[date] = None
    phone_number: Optional[str] = None
    employee_badge: Optional[str] = None
    role: user_role = user_role.rcm_engineer
    work_shift: turn = turn.daytime

class UserCreate(UserBase):
    password: str 

class UserResponse(UserBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True