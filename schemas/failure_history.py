"""
Esquemas Pydantic para el Historial de Fallas.

Aplica validaciones estrictas para evitar datos de campo inconsistentes 
(ej. reportar fallas en el futuro o tiempos negativos).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, field_validator

class FailureHistoryBase(BaseModel):
    """Campos base para el registro de una avería."""
    equipment_id: uuid.UUID
    failure_date: datetime
    failure_mode: str
    severity: str
    description: str
    metric_at_failure_id: Optional[uuid.UUID] = None
    fmea_analysis_id: Optional[uuid.UUID] = None
    downtime_hours: Optional[float] = None

    @field_validator("failure_date")
    @classmethod
    def validate_failure_date(cls, v: datetime) -> datetime:
        """Evita errores de tipeo bloqueando fechas en el futuro."""
        if v > datetime.now(timezone.utc):
            raise ValueError("La fecha de falla no puede ser una fecha en el futuro.")
        return v

    @field_validator("downtime_hours")
    @classmethod
    def validate_downtime(cls, v: Optional[float]) -> Optional[float]:
        """Asegura que el tiempo de inactividad tenga lógica física."""
        if v is not None and v < 0:
            raise ValueError("Las horas de inactividad (downtime) no pueden ser negativas.")
        return v

class FailureHistoryCreate(FailureHistoryBase):
    """Esquema para reportar una nueva avería. El autor se inyecta desde el token."""
    pass

class FailureHistoryUpdate(BaseModel):
    """
    Esquema para actualizaciones parciales. 
    Permite corregir detalles técnicos si se evalúa mejor la rotura a posteriori.
    """
    failure_mode: Optional[str] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    fmea_analysis_id: Optional[uuid.UUID] = None
    downtime_hours: Optional[float] = None

    @field_validator("downtime_hours")
    @classmethod
    def validate_downtime_update(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Las horas de inactividad no pueden ser negativas.")
        return v

class FailureHistoryResponse(FailureHistoryBase):
    """Salida serializada del reporte de falla."""
    id: uuid.UUID
    reported_by: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True