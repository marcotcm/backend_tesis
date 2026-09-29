"""
Modelo ORM para el Historial de Mantenimientos (Maintenance History).

Mapea la tabla 'public.maintenance_history'.
Es el registro definitivo e inmutable de los trabajos ejecutados en planta,
conectando la acción tomada con métricas de entrada/salida y posibles fallas.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, Numeric, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from db.session import Base

class MaintenanceHistory(Base):
    __tablename__ = "maintenance_history"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id = Column(UUID(as_uuid=True), ForeignKey("public.equipments.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Enlaces lógicos a la planificación y averías
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("public.work_orders.id", ondelete="SET NULL"), nullable=True)
    was_failure_driven = Column(Boolean, nullable=False, default=False)
    failure_id = Column(UUID(as_uuid=True), ForeignKey("public.failure_history.id", ondelete="SET NULL"), nullable=True)
    
    # Detalles de la ejecución
    execution_date = Column(DateTime(timezone=True), nullable=False)
    action_taken = Column(Text, nullable=False)
    replaced_parts = Column(JSONB, nullable=True)
    real_downtime_hours = Column(Numeric, nullable=True)
    
    # Condiciones del equipo antes y después del trabajo
    start_metric_id = Column(UUID(as_uuid=True), ForeignKey("public.equipment_metrics_history.id", ondelete="RESTRICT"), nullable=True)
    end_metric_id = Column(UUID(as_uuid=True), ForeignKey("public.equipment_metrics_history.id", ondelete="RESTRICT"), nullable=True)
    
    # Trazabilidad
    executed_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)