"""
Esquemas Pydantic para la taxonomía de equipos.
"""

import uuid
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel

class EquipmentTaxonomyBase(BaseModel):
    name: str
    level: Literal["planta", "sistema", "subsistema", "componente"]
    description: Optional[str] = None
    

class EquipmentTaxonomyCreate(EquipmentTaxonomyBase):
    pass

class EquipmentTaxonomyUpdate(BaseModel):
    parent_id: Optional[uuid.UUID] = None
    name: Optional[str] = None
    level: Optional[Literal["planta", "sistema", "subsistema", "componente"]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class EquipmentTaxonomyResponse(EquipmentTaxonomyBase):
    id: uuid.UUID
    is_active: bool 
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True