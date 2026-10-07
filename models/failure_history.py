"""
Modelo ORM para el Historial de Fallas (Failure History).

Mapea la tabla 'public.failure_history'.
Es el registro central de eventos de rotura o paradas no programadas,
vital para el cálculo del MTBF (Tiempo Medio Entre Fallas) y MTTR (Tiempo Medio de Reparación).
"""

import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Numeric, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, ENUM
from db.session import Base



# Enum nativo de PostgreSQL


class FailureHistory(Base):
    __tablename__ = "failure_history"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id = Column(UUID(as_uuid=True), ForeignKey("public.equipments.id", ondelete="CASCADE"), nullable=False, index=True)
    
    failure_date = Column(DateTime(timezone=True), nullable=False)
    failure_mode = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    
    # Enlaces opcionales a contexto técnico
    metric_at_failure_id = Column(UUID(as_uuid=True), ForeignKey("public.equipment_metrics_history.id", ondelete="RESTRICT"), nullable=True)
    fmea_analysis_id = Column(UUID(as_uuid=True), ForeignKey("public.fmea_analyses.id", ondelete="SET NULL"), nullable=True)
    
    downtime_hours = Column(Numeric, nullable=True)
    
    # Trazabilidad
    reported_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)