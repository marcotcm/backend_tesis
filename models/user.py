from sqlalchemy import Column, String, DateTime, Boolean, Date, Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import enum
from db.session import Base

# Definición de ENUMs en Python para que coincidan con PostgreSQL
class user_role(str, enum.Enum):
    admin = "admin"
    rcm_engineer = "rcm_engineer"
    technical_auditor = "technical_auditor"

class turn(str, enum.Enum):
    daytime = "daytime"
    nighttime = "nighttime"

class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=True), primary_key=True) # Referencia auth.users
    email = Column(String(255), unique=True, nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    identification_id = Column(String(20), unique=True, nullable=False, index=True)
    birth_date = Column(Date, nullable=True)
    phone_number = Column(String(20), nullable=True)
    employee_badge = Column(String(50), unique=True, nullable=True, index=True)
    
    # Uso de los ENUMs definidos
    role = Column(SQLAlchemyEnum(user_role), nullable=False, default=user_role.rcm_engineer)
    work_shift = Column(SQLAlchemyEnum(turn), nullable=False, default=turn.daytime)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    deleted_at = Column(DateTime(timezone=True), nullable=True)