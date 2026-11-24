"""
Modelos ORM para Alarmas Industriales ISA-18.2 y Rollups Time-Series por hora.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from db.session import Base


class IndustrialAlarm(Base):
    __tablename__ = "industrial_alarms"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.equipments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_key = Column(String(80), nullable=False)
    state = Column(String(24), nullable=False, default="ACTIVE_UNACK")
    priority = Column(String(16), nullable=False, default="P2_HIGH")
    message = Column(Text, nullable=False)
    trigger_value = Column(Numeric(12, 3), nullable=True)
    threshold_value = Column(Numeric(12, 3), nullable=True)
    occurrence_count = Column(Integer, nullable=False, default=1)
    acknowledged_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    ack_notes = Column(Text, nullable=True)
    shelved_until = Column(DateTime(timezone=True), nullable=True)
    triggered_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_seen_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    cleared_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class EquipmentMetricHourly(Base):
    __tablename__ = "equipment_metrics_hourly"
    __table_args__ = {"schema": "public"}

    equipment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.equipments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    bucket_hour = Column(DateTime(timezone=True), primary_key=True)
    sample_count = Column(Integer, nullable=False, default=0)
    avg_vibration = Column(Numeric(10, 3), nullable=True)
    max_vibration = Column(Numeric(10, 3), nullable=True)
    avg_temperature = Column(Numeric(10, 3), nullable=True)
    max_temperature = Column(Numeric(10, 3), nullable=True)
    avg_pressure = Column(Numeric(10, 3), nullable=True)
    max_pressure = Column(Numeric(10, 3), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
