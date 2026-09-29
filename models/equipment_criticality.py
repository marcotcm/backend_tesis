import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base


class EquipmentCriticality(Base):
    __tablename__ = "equipment_criticality"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id = Column(UUID(as_uuid=True), ForeignKey("public.equipments.id"), nullable=False, unique=True)
    safety_impact_score = Column(Integer, nullable=False)
    environmental_impact_score = Column(Integer, nullable=False)
    operational_impact_score = Column(Integer, nullable=False)
    maintenance_cost_score = Column(Integer, nullable=False)
    rpn_score = Column(Integer, nullable=False)
    criticality_level = Column(String, nullable=False)
    evaluated_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)
    evaluated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
