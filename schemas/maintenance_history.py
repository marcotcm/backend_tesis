"""
Esquemas Pydantic para el Historial de Mantenimientos.

Valida la congruencia de los datos finales (ej. que no se registren mantenimientos
en el futuro y que el downtime no sea negativo).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, field_validator, model_validator

class MaintenanceHistoryBase(BaseModel):
    equipment_id: uuid.UUID
    work_order_id: Optional[uuid.UUID] = None
    was_failure_driven: bool = False
    failure_id: Optional[uuid.UUID] = None
    execution_date: datetime
    action_taken: str
    replaced_parts: Optional[List[Dict[str, Any]]] = None
    real_downtime_hours: Optional[float] = None
    start_metric_id: Optional[uuid.UUID] = None
    end_metric_id: Optional[uuid.UUID] = None

    @field_validator("execution_date")
    @classmethod
    def validate_execution_date(cls, v: datetime) -> datetime:
        if v > datetime.now(timezone.utc):
            raise ValueError("La fecha de ejecución no puede ser en el futuro.")
        return v

    @field_validator("real_downtime_hours")
    @classmethod
    def validate_downtime(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Las horas de inactividad reales no pueden ser negativas.")
        return v

    @model_validator(mode='after')
    def validate_failure_logic(self) -> 'MaintenanceHistoryBase':
        """Regla cruzada: Si fue motivado por falla, se sugiere fuertemente tener el failure_id (aunque el esquema SQL lo permite nulo)."""
        if self.was_failure_driven and not self.failure_id:
            pass # Aquí podrías levantar un ValueError si deseas forzar la regla restrictiva.
        return self

class MaintenanceHistoryCreate(MaintenanceHistoryBase):
    pass

class MaintenanceHistoryUpdate(BaseModel):
    action_taken: Optional[str] = None
    replaced_parts: Optional[List[Dict[str, Any]]] = None
    real_downtime_hours: Optional[float] = None
    end_metric_id: Optional[uuid.UUID] = None

    @field_validator("real_downtime_hours")
    @classmethod
    def validate_downtime_update(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Las horas de inactividad no pueden ser negativas.")
        return v

class MaintenanceHistoryResponse(MaintenanceHistoryBase):
    id: uuid.UUID
    executed_by: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True