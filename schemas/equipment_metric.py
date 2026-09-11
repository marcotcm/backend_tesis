import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, field_validator

class EquipmentMetricBase(BaseModel):
    equipment_id: uuid.UUID
    temperature_celsius: Optional[float] = None
    vibration_mm_s: Optional[float] = None
    operating_hours: Optional[float] = None
    specific_metrics: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None

    @field_validator("temperature_celsius")
    @classmethod
    def validate_temperature(cls, v: Optional[float]) -> Optional[float]:
        """Validación en espejo del CHECK (temperature_celsius BETWEEN -50 AND 1000)"""
        if v is not None and not (-50 <= v <= 1000):
            raise ValueError("La temperatura debe registrarse en un rango válido entre -50°C y 1000°C.")
        return v

    @field_validator("vibration_mm_s")
    @classmethod
    def validate_vibration(cls, v: Optional[float]) -> Optional[float]:
        """Validación en espejo del CHECK (vibration_mm_s >= 0)"""
        if v is not None and v < 0:
            raise ValueError("La vibración no puede ser un valor negativo.")
        return v
        
    @field_validator("operating_hours")
    @classmethod
    def validate_operating_hours(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Las horas de operación no pueden ser negativas.")
        return v

class EquipmentMetricCreate(EquipmentMetricBase):
    """Esquema de entrada. No pide 'recorded_by' porque el backend lo inyectará del token JWT."""
    pass

class EquipmentMetricResponse(EquipmentMetricBase):
    """Esquema de salida con datos autogenerados por la base de datos."""
    id: uuid.UUID
    recorded_by: uuid.UUID
    recorded_at: datetime

    class Config:
        from_attributes = True