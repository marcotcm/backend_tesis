import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base


class AICorrection(Base):
    __tablename__ = "ai_corrections"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recommendation_id = Column(UUID(as_uuid=True), ForeignKey("public.ai_recommendations.id"), nullable=False, unique=True)
    corrected_text = Column(Text, nullable=False)
    corrected_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
