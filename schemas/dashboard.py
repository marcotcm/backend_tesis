from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class EquipmentStats(BaseModel):
    total: int
    operational: int
    standby: int
    under_maintenance: int
    failed: int
    inactive: int
    critical: int


class WorkOrderStats(BaseModel):
    total_active: int
    pending: int
    in_progress: int
    completed_this_month: int
    overdue: int


class FailureStats(BaseModel):
    total_recorded: int
    average_downtime_hours: Optional[float] = None
    total_downtime_hours: Optional[float] = None
    total_operating_hours: Optional[float] = None
    mtbf_hours: Optional[float] = None
    mttr_hours: Optional[float] = None
    inherent_availability_pct: Optional[float] = None


class RecentActivity(BaseModel):
    id: UUID
    type: Literal["work_order", "failure", "maintenance", "recommendation"]
    title: str
    description: str
    timestamp: datetime
    equipment_tag: str


class MroCostStats(BaseModel):
    total_skus: int = 0
    low_stock_count: int = 0
    out_of_stock_count: int = 0
    total_inventory_value: float = 0.0
    month_labor_cost: float = 0.0
    month_parts_cost: float = 0.0
    month_total_maintenance_cost: float = 0.0
    month_downtime_hours: float = 0.0
    month_downtime_cost: float = 0.0


class DashboardSummary(BaseModel):
    equipment_stats: EquipmentStats
    work_order_stats: WorkOrderStats
    failure_stats: FailureStats
    mro_stats: Optional[MroCostStats] = None
    recent_activity: list[RecentActivity]
