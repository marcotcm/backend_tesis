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
    average_downtime_hours: Optional[float]


class RecentActivity(BaseModel):
    id: UUID
    type: Literal["work_order", "failure", "maintenance", "recommendation"]
    title: str
    description: str
    timestamp: datetime
    equipment_tag: str


class DashboardSummary(BaseModel):
    equipment_stats: EquipmentStats
    work_order_stats: WorkOrderStats
    failure_stats: FailureStats
    recent_activity: list[RecentActivity]
