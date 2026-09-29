"""
Modelo ORM para las Órdenes de Trabajo (Work Orders).

Mapea la tabla 'public.work_orders'.
Controla la ejecución física de las rutinas de mantenimiento (preventivo, 
correctivo, etc.), gestionando la asignación de técnicos, estados y prioridades.
"""

import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, ENUM
from db.session import Base

class WorkOrderStatus(str, enum.Enum):
    """Estados del ciclo de vida de una Orden de Trabajo."""
    pendiente = "Pendiente"
    en_proceso = "En Proceso"
    terminado = "Terminado"
    cancelado = "Cancelado"

class WorkOrderPriority(str, enum.Enum):
    """Niveles de prioridad para la planificación y despacho."""
    baja = "Baja"
    normal = "Normal"
    alta = "Alta"
    urgente = "Urgente"

# Vinculación con los ENUMs creados a nivel de PostgreSQL
wo_status_enum = ENUM(WorkOrderStatus, name="wo_status", schema="public", create_type=False)
wo_priority_enum = ENUM(WorkOrderPriority, name="wo_priority", schema="public", create_type=False)

class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    maintenance_id = Column(UUID(as_uuid=True), ForeignKey("public.maintenances.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    status = Column(wo_status_enum, nullable=False, default=WorkOrderStatus.pendiente, index=True)
    priority = Column(wo_priority_enum, nullable=False, default=WorkOrderPriority.normal)
    
    # Tiempos de planificación y ejecución
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    technician_notes = Column(Text, nullable=True)
    
    # Trazabilidad
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)