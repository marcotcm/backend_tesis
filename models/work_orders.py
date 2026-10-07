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
from sqlalchemy.dialects.postgresql import UUID
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

class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    maintenance_id = Column(UUID(as_uuid=True), ForeignKey("public.maintenances.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # La BD existente usa VARCHAR con CHECK, no tipos ENUM nativos de PostgreSQL.
    status = Column(String, nullable=False, default=WorkOrderStatus.pendiente.value, index=True)
    priority = Column(String, nullable=False, default=WorkOrderPriority.normal.value)
    
    # Tiempos de planificación y ejecución
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    technician_notes = Column(Text, nullable=True)
    
    # Trazabilidad
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)