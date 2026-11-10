"""
schemas/chatbot.py
Esquemas Pydantic para el Asistente Conversacional RCM (Chatbot).
Soporta generación de respuestas técnicas detalladas por activo,
propuestas interactivas de acciones y creación física de Órdenes de Trabajo
y Planes de Mantenimiento en PostgreSQL.
"""

from typing import List, Optional, Literal, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: Literal["usuario", "asesor", "user", "assistant", "system"]
    content: str
    timestamp: Optional[datetime] = None

class ChatRequest(BaseModel):
    message: Optional[str] = Field(default="", description="Mensaje o consulta técnica del usuario.")
    session_id: Optional[str] = Field(default=None, description="Identificador único de la sesión conversacional.")
    equipment_id: Optional[str] = Field(default=None, description="UUID o TAG del activo industrial (opcional).")
    include_db_context: bool = Field(default=True, description="Si es True, inyecta telemetría real y AMEF del equipo desde PostgreSQL.")

class ChatClearRequest(BaseModel):
    session_id: str

class ActionProposal(BaseModel):
    """Acción recomendada por la IA para ejecución con 1 clic."""
    type: Literal["create_work_order", "create_maintenance_plan"]
    equipment_id: Optional[str] = None
    equipment_tag: Optional[str] = None
    equipment_name: Optional[str] = None
    title: str
    priority: Optional[str] = "Alta"
    description: Optional[str] = None
    suggested_frequency_days: Optional[int] = 30

class ActionExecuted(BaseModel):
    """Confirmación de acción generada directamente en la base de datos."""
    type: Literal["work_order_created", "maintenance_plan_created"]
    id: str
    equipment_id: str
    equipment_tag: str
    title: str
    status: Optional[str] = None
    priority: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class ChatResponse(BaseModel):
    success: bool
    response: str
    session_id: str
    suggestions: List[str] = Field(default_factory=list)
    recommendations: Optional[str] = None
    detected_equipment: Optional[Dict[str, Any]] = None
    rcm_data: Optional[Dict[str, Any]] = None
    action_proposal: Optional[ActionProposal] = None
    action_executed: Optional[ActionExecuted] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ChatHistoryResponse(BaseModel):
    success: bool
    session_id: str
    history: List[ChatMessage]

class ChatClearResponse(BaseModel):
    success: bool
    message: str

class QuickQuestionItem(BaseModel):
    id: str
    label: str
    question: str
    category: str

# Esquemas para creación directa desde el Copiloto
class CreateWorkOrderFromChatRequest(BaseModel):
    equipment_id: Optional[str] = None
    equipment_tag: Optional[str] = None
    title: str
    priority: Literal["Baja", "Normal", "Alta", "Urgente"] = "Alta"
    technician_notes: Optional[str] = None
    scheduled_for: Optional[datetime] = None

class CreateMaintenancePlanFromChatRequest(BaseModel):
    equipment_id: Optional[str] = None
    equipment_tag: Optional[str] = None
    title: str
    maintenance_type: Literal["Preventivo", "Predictivo", "Correctivo", "Por Condición"] = "Predictivo"
    frequency_days: Optional[int] = 30
    description: Optional[str] = None

class ChatbotActionResponse(BaseModel):
    success: bool
    message: str
    created_id: str
    entity_type: Literal["work_order", "maintenance_plan"]
    data: Dict[str, Any]
