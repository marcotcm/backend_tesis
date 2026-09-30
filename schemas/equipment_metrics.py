"""
Esquemas Pydantic para Serialización y Validación de Métricas de Equipos.

Asegura que las lecturas físicas ingresadas al sistema tengan coherencia técnica
y se encuentren dentro de los umbrales lógicos de operación.
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, field_validator

class EquipmentMetricBase(BaseModel):
    """Campos base compartidos por los esquemas de métricas."""
    equipment_id: uuid.UUID
    temperature_celsius: Optional[float] = None
    vibration_mm_s: Optional[float] = None
    operating_hours: Optional[float] = None
    specific_metrics: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None

    @field_validator("temperature_celsius")
    @classmethod
    def validate_temperature(cls, v: Optional[float]) -> Optional[float]:
        """Valida que la temperatura esté en rangos industriales lógicos (-50°C a 1000°C)."""
        if v is not None and (v < -50 or v > 1000):
            raise ValueError("La temperatura debe estar entre -50°C y 1000°C.")
        return v

    @field_validator("vibration_mm_s")
    @classmethod
    def validate_vibration(cls, v: Optional[float]) -> Optional[float]:
        """Valida que la amplitud de vibración no sea un valor negativo."""
        if v is not None and v < 0:
            raise ValueError("La vibración (mm/s) no puede ser un valor negativo.")
        return v
        
    @field_validator("operating_hours")
    @classmethod
    def validate_operating_hours(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Las horas de operación no pueden ser negativas.")
        return v

class EquipmentMetricCreate(EquipmentMetricBase):
    """Esquema de entrada para registrar una nueva lectura. El recorded_by se inyecta en el servicio."""
    pass

class EquipmentMetricUpdate(BaseModel):
    """
    Esquema restrictivo para actualizaciones.
    Por integridad de RCM, las métricas físicas no deberían mutar. 
    Solo se permite actualizar notas u observaciones técnicas de la lectura.
    """
    notes: Optional[str] = None
    specific_metrics: Optional[Dict[str, Any]] = None

class EquipmentMetricResponse(EquipmentMetricBase):
    """Esquema de salida serializado que expone la lectura registrada."""
    id: uuid.UUID
    recorded_by: uuid.UUID
    recorded_at: datetime

    class Config:
        from_attributes = True