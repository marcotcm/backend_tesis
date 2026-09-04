"""
Modelo ORM para la entidad principal de activos/equipos.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base


class Equipment(Base):
    __tablename__ = "equipments"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    taxonomy_id = Column(UUID(as_uuid=True), ForeignKey("public.equipment_taxonomy.id"), nullable=False)
    tag_number = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    brand = Column(String, nullable=True)
    model = Column(String, nullable=True)
    equipment_type = Column(String, nullable=False)
    operational_status = Column(String, nullable=False, default="operational")
    technical_specifications = Column(JSON, nullable=True)
    function_description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
