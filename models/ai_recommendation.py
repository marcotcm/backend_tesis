import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base


class AIRecommendation(Base):
    __tablename__ = "ai_recommendations"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id = Column(UUID(as_uuid=True), ForeignKey("public.equipments.id"), nullable=False)
    trigger_source = Column(String, nullable=False)
    trigger_reference_id = Column(UUID(as_uuid=True), nullable=True)
    recommendation_text = Column(Text, nullable=False)
    confidence_score = Column(Numeric(5, 2), nullable=False)
    prediction_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="Pendiente")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
