"""
Esquemas Pydantic para el módulo MRO (Repuestos) y su consumo en Órdenes de Trabajo.
"""

import uuid
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class SparePartBase(BaseModel):
    sku: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    category: str = Field(default="General", max_length=80)
    unit_of_measure: str = Field(default="unidad", max_length=30)
    stock_qty: float = Field(default=0.0, ge=0)
    min_stock_qty: float = Field(default=0.0, ge=0)
    unit_cost: float = Field(default=0.0, ge=0)
    warehouse_location: Optional[str] = Field(default=None, max_length=120)
    supplier: Optional[str] = Field(default=None, max_length=160)
    taxonomy_id: Optional[uuid.UUID] = None
    is_active: bool = True


class SparePartCreate(SparePartBase):
    pass


class SparePartUpdate(BaseModel):
    sku: Optional[str] = Field(default=None, min_length=1, max_length=80)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=80)
    unit_of_measure: Optional[str] = Field(default=None, max_length=30)
    stock_qty: Optional[float] = Field(default=None, ge=0)
    min_stock_qty: Optional[float] = Field(default=None, ge=0)
    unit_cost: Optional[float] = Field(default=None, ge=0)
    warehouse_location: Optional[str] = Field(default=None, max_length=120)
    supplier: Optional[str] = Field(default=None, max_length=160)
    taxonomy_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


class SparePartStockAdjust(BaseModel):
    operation: Literal["add", "subtract", "set"]
    quantity: float = Field(..., ge=0)
    reason: Optional[str] = None


class SparePartResponse(SparePartBase):
    id: uuid.UUID
    is_low_stock: bool = False
    inventory_value: float = 0.0
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SparePartsSummary(BaseModel):
    total_skus: int
    low_stock_count: int
    out_of_stock_count: int
    total_inventory_value: float


class WorkOrderPartConsumeRequest(BaseModel):
    spare_part_id: uuid.UUID
    quantity_used: float = Field(..., gt=0)
    notes: Optional[str] = None


class WorkOrderPartResponse(BaseModel):
    id: uuid.UUID
    work_order_id: uuid.UUID
    spare_part_id: uuid.UUID
    spare_part_sku: str
    spare_part_name: str
    unit_of_measure: str
    quantity_used: float
    unit_cost_snapshot: float
    total_cost: float
    notes: Optional[str] = None
    created_at: datetime
