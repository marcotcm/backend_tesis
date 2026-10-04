"""
Modelo ORM para la jerarquía de clasificación de equipos.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base

class EquipmentTaxonomy(Base):
    __tablename__ = "equipment_taxonomy"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("public.equipment_taxonomy.id"), nullable=True)
    name = Column(String, nullable=False)
    
    # Se mantiene como String (validado por Pydantic Literal)
    level = Column(String, nullable=False)
    
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("public.users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Columna para borrado lógico real
    deleted_at = Column(DateTime(timezone=True), nullable=True)