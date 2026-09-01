"""
Modelo ORM para la Tabla de Usuarios del Sistema RCM.

Mapea la tabla 'public.users' y sincroniza su identificador primario
directamente con el UUID de la tabla 'auth.users' de Supabase Auth.
"""

import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID, ENUM
from db.session import Base

class UserRole(str, enum.Enum):
    """Roles operativos con control de acceso granular en la plataforma RCM."""
    admin = "admin"
    rcm_engineer = "rcm_engineer"
    technical_auditor = "technical_auditor"

class Turn(str, enum.Enum):
    """Turnos de trabajo operativo para el personal de planta."""
    daytime = "daytime"
    nighttime = "nighttime"

# Vinculación explícita con los tipos ENUM nativos preexistentes en PostgreSQL (public schema)
user_role_enum = ENUM(UserRole, name="user_role", schema="public", create_type=False)
turn_enum = ENUM(Turn, name="turn", schema="public", create_type=False)

class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    # Identificador único UUID vinculado 1:1 con auth.users(id)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    identification_id = Column(String, unique=True, nullable=False, index=True)  # Cédula (V-, E-, P-)
    birth_date = Column(Date, nullable=True)
    phone_number = Column(String, nullable=True)
    employee_badge = Column(String, unique=True, nullable=True)  # Número de ficha/carnet
    
    # Atributos enumerados
    role = Column(user_role_enum, nullable=False, default=UserRole.rcm_engineer)
    work_shift = Column(turn_enum, nullable=False, default=Turn.daytime)
    
    # Metadatos del perfil y control de estado
    specialty = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Marca temporal para soft-delete