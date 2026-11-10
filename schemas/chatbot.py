"""
schemas/chatbot.py
Esquemas Pydantic para el Asistente Conversacional RCM (Chatbot).
Inspirado en la arquitectura modular de maxton_ai_back y adaptado
al sistema de confiabilidad industrial y mantenimiento predictivo Heimdall.
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

class ChatResponse(BaseModel):
    success: bool
    response: str
    session_id: str
    suggestions: List[str] = Field(default_factory=list)
    recommendations: Optional[str] = None
    detected_equipment: Optional[Dict[str, Any]] = None
    rcm_data: Optional[Dict[str, Any]] = None
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
