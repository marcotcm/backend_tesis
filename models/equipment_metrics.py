"""
Modelo ORM para el Historial de Métricas de Equipos.

Mapea la tabla 'public.equipment_metrics_history'. 
Almacena lecturas de sensores o inspecciones manuales, manteniendo 
trazabilidad del técnico responsable de la medición.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Numeric, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from db.session import Base

class EquipmentMetricHistory(Base):
    __tablename__ = "equipment_metrics_history"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id = Column(UUID(as_uuid=True), ForeignKey("public.equipments.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Métricas físicas con restricciones a nivel de BD
    temperature_celsius = Column(Numeric, nullable=True)
    vibration_mm_s = Column(Numeric, nullable=True)
    operating_hours = Column(Numeric, nullable=True)
    
    # Campo flexible para otras variables (Presión, Flujo, RPM, etc.)
    specific_metrics = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)
    
    # Trazabilidad
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="RESTRICT"), nullable=False)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)