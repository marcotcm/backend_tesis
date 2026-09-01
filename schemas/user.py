"""
Esquemas Pydantic para Serialización y Validación de Datos de Usuario.

Asegura que los datos entrantes cumplan con las reglas de negocio y restricciones
(Regex para cédulas venezolanas, teléfonos y verificación de mayoría de edad).
"""

import re
import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator
from models.user import UserRole, Turn

class UserBase(BaseModel):
    """Campos base compartidos por múltiples esquemas de usuario."""
    email: EmailStr
    first_name: str
    last_name: str
    identification_id: str
    birth_date: Optional[date] = None
    phone_number: Optional[str] = None
    employee_badge: Optional[str] = None
    role: UserRole = UserRole.rcm_engineer
    work_shift: Turn = Turn.daytime
    specialty: Optional[str] = None

    @field_validator("identification_id")
    @classmethod
    def validate_identification(cls, v: str) -> str:
        """Valida que la cédula cumpla con el formato legal de Venezuela (V-, E-, P- seguido de 6 a 9 dígitos)."""
        if not re.match(r"^[VEP]-[0-9]{6,9}$", v):
            raise ValueError("La identificación debe tener un formato válido (e.g., V-12345678, E-12345678, P-12345678).")
        return v

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        """Valida códigos de área o celulares nacionales venezolanos (+58 o 0 seguido de código de operadora)."""
        if v is not None and not re.match(r"^(\+58|0)(412|414|424|416|426|2[0-9]{2})[0-9]{7}$", v):
            raise ValueError("El número de teléfono no cumple con el formato de numeración telefónica válido.")
        return v

    @field_validator("birth_date")
    @classmethod
    def validate_adult(cls, v: Optional[date]) -> Optional[date]:
        """Garantiza la mayoría de edad (mínimo 18 años) según la fecha de nacimiento."""
        if v is not None:
            today = date.today()
            age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
            if age < 18:
                raise ValueError("El usuario debe ser mayor de edad (+18 años) para ser registrado.")
        return v

class UserCreate(UserBase):
    """Esquema de entrada para el registro de nuevos usuarios en el sistema."""
    password: str

class UserUpdate(BaseModel):
    """Esquema para actualizaciones parciales (PATCH). Todos los campos son opcionales."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    employee_badge: Optional[str] = None
    work_shift: Optional[Turn] = None
    specialty: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None

    @field_validator("phone_number")
    @classmethod
    def validate_phone_update(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^(\+58|0)(412|414|424|416|426|2[0-9]{2})[0-9]{7}$", v):
            raise ValueError("El número de teléfono no cumple con el formato válido.")
        return v

class UserResponse(UserBase):
    """Esquema de salida serializado que expone la información pública del usuario."""
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True  # Compatibilidad con objetos ORM de SQLAlchemy

class UserLogin(BaseModel):
    """Credenciales requeridas para el inicio de sesión."""
    email: EmailStr
    password: str

class TokenRefreshRequest(BaseModel):
    """Cuerpo de solicitud para refrescar un token de acceso expirado."""
    refresh_token: str

class TokenResponse(BaseModel):
    """Estructura de respuesta que emite los tokens JWT junto con el perfil cargado."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse

class ForgotPasswordRequest(BaseModel):
    """Cuerpo de solicitud para iniciar el proceso de recuperación de contraseña."""
    email: EmailStr