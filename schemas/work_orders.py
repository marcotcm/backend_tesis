"""
Esquemas Pydantic para Serialización y Validación de Órdenes de Trabajo.

Asegura la congruencia temporal (tiempos de inicio y fin lógicos) y 
la correcta estructura de datos antes de impactar el planificador.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator
from models.work_orders import WorkOrderStatus, WorkOrderPriority

class WorkOrderBase(BaseModel):
    """Atributos fundamentales compartidos en el dominio de Órdenes de Trabajo."""
    maintenance_id: uuid.UUID
    assigned_to: Optional[uuid.UUID] = None
    status: WorkOrderStatus = WorkOrderStatus.pendiente
    priority: WorkOrderPriority = WorkOrderPriority.normal
    scheduled_for: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    technician_notes: Optional[str] = None

    @model_validator(mode='after')
    def validate_execution_dates(self) -> 'WorkOrderBase':
        """Regla RCM: La fecha de finalización no puede ser anterior a la de inicio."""
        if self.started_at and self.completed_at:
            if self.completed_at < self.started_at:
                raise ValueError("La fecha de finalización (completed_at) no puede ser anterior a la fecha de inicio (started_at).")
        return self

class WorkOrderCreate(WorkOrderBase):
    """
    Datos requeridos para emitir una nueva orden. 
    El campo 'created_by' se omitirá aquí porque se inyectará en la capa de servicios.
    """
    pass

class WorkOrderUpdate(BaseModel):
    """
    Campos permitidos para actualización. 
    Se usa comúnmente cuando el técnico inicia o termina el trabajo y añade sus notas.
    """
    assigned_to: Optional[uuid.UUID] = None
    status: Optional[WorkOrderStatus] = None
    priority: Optional[WorkOrderPriority] = None
    scheduled_for: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    technician_notes: Optional[str] = None

    @model_validator(mode='after')
    def validate_dates_on_update(self) -> 'WorkOrderUpdate':
        if self.started_at and self.completed_at:
            if self.completed_at < self.started_at:
                raise ValueError("Incongruencia temporal: La orden no puede completarse antes de iniciarse.")
        return self

class WorkOrderResponse(WorkOrderBase):
    """Salida serializada del registro para exponer al cliente API."""
    id: uuid.UUID
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True