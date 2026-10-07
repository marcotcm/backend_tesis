import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base


class FMEAAnalysis(Base):
    __tablename__ = "fmea_analyses"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id = Column(UUID(as_uuid=True), ForeignKey("public.equipments.id"), nullable=False, index=True)

    title = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDIENTE")
    severity = Column(Integer, nullable=False)
    occurrence = Column(Integer, nullable=False)
    detection = Column(Integer, nullable=False)
    rpn_score = Column(Integer, nullable=False, default=0)

    description = Column(Text, nullable=False)
    causes = Column(JSON, nullable=False, default=list)
    effects = Column(JSON, nullable=False, default=list)
    current_controls = Column(JSON, nullable=False, default=list)
    recommended_actions = Column(JSON, nullable=False, default=list)

    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
