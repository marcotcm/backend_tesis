"""
Esquemas Pydantic para Consola de Alarmas ISA-18.2 y Series Temporales Horarias.
"""

import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class IndustrialAlarmResponse(BaseModel):
    id: uuid.UUID
    equipment_id: uuid.UUID
    equipment_tag: str
    equipment_name: str
    metric_key: str
    state: str
    priority: str
    message: str
    trigger_value: Optional[float] = None
    threshold_value: Optional[float] = None
    occurrence_count: int = 1
    acknowledged_by: Optional[uuid.UUID] = None
    acknowledged_by_name: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    ack_notes: Optional[str] = None
    shelved_until: Optional[datetime] = None
    triggered_at: datetime
    last_seen_at: datetime
    cleared_at: Optional[datetime] = None


class AlarmAckRequest(BaseModel):
    ack_notes: Optional[str] = Field(default=None, max_length=500)


class AlarmShelveRequest(BaseModel):
    hours: float = Field(default=2.0, gt=0, le=72)
    reason: Optional[str] = Field(default=None, max_length=500)


class AlarmsSummary(BaseModel):
    active_unack: int = 0
    active_ack: int = 0
    cleared_unack: int = 0
    shelved: int = 0
    p1_active: int = 0


class MetricTimeSeriesPoint(BaseModel):
    bucket: datetime
    vibration_mm_s: Optional[float] = None
    max_vibration_mm_s: Optional[float] = None
    temperature_celsius: Optional[float] = None
    max_temperature_celsius: Optional[float] = None
    pressure_psi: Optional[float] = None
    sample_count: int = 0
