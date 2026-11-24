"""
Modelos ORM para el Almacén MRO (Repuestos) y Consumo en Órdenes de Trabajo.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from db.session import Base


class SparePart(Base):
    __tablename__ = "spare_parts"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku = Column(String(80), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(80), nullable=False, default="General")
    unit_of_measure = Column(String(30), nullable=False, default="unidad")
    stock_qty = Column(Numeric(12, 2), nullable=False, default=0)
    min_stock_qty = Column(Numeric(12, 2), nullable=False, default=0)
    unit_cost = Column(Numeric(12, 2), nullable=False, default=0)
    warehouse_location = Column(String(120), nullable=True)
    supplier = Column(String(160), nullable=True)
    taxonomy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.equipment_taxonomy.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id", ondelete="SET NULL"),
        nullable=True,
    )
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


class WorkOrderPart(Base):
    __tablename__ = "work_order_parts"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    spare_part_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.spare_parts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quantity_used = Column(Numeric(12, 2), nullable=False)
    unit_cost_snapshot = Column(Numeric(12, 2), nullable=False, default=0)
    total_cost = Column(Numeric(12, 2), nullable=False, default=0)
    notes = Column(Text, nullable=True)
    recorded_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
