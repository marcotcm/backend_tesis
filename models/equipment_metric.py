import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Numeric, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from db.session import Base

class EquipmentMetric(Base):
    __tablename__ = "equipment_metrics_history"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id = Column(UUID(as_uuid=True), ForeignKey("public.equipments.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Métricas físicas principales
    temperature_celsius = Column(Numeric, nullable=True)
    vibration_mm_s = Column(Numeric, nullable=True)
    operating_hours = Column(Numeric, nullable=True)
    
    # Campo dinámico para variables específicas (Presión, Voltaje, etc.)
    specific_metrics = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)
    
    # Trazabilidad
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="RESTRICT"), nullable=False)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Nota: Las relaciones (relationship) se definen aquí si tienes los modelos creados, 
    # ej: equipment = relationship("Equipment", back_populates="metrics")