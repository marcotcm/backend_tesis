"""
api/v1/endpoints/chatbot.py
Endpoints del Asistente Conversacional RCM (Chatbot) con Inteligencia Artificial.
Inspirado en la arquitectura modular de maxton_ai_back (chatbot.controller.js / chatbot.routes.js)
y adaptado al backend FastAPI de Heimdall RCM.
Incluye endpoints de chat, análisis multimodal, preguntas frecuentes,
y creación física de Órdenes de Trabajo y Planes de Mantenimiento en PostgreSQL.
"""

import uuid
from typing import Optional, List
import jwt
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from models.user import User
from crud.user import get_user_by_id
from schemas.chatbot import (
    ChatRequest,
    ChatResponse,
    ChatClearRequest,
    ChatClearResponse,
    ChatHistoryResponse,
    ChatMessage,
    QuickQuestionItem,
    CreateWorkOrderFromChatRequest,
    CreateMaintenancePlanFromChatRequest,
    ChatbotActionResponse,
)
from services.rcm_chatbot_service import rcm_chatbot_service

router = APIRouter()

bearer_scheme = HTTPBearer(auto_error=False)

async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Extrae el usuario autenticado si se provee Bearer Token válido, o None si no hay token."""
    if not credentials or not credentials.credentials:
        return None
    try:
        payload = jwt.decode(
            credentials.credentials,
            options={"verify_signature": False},
            algorithms=["ES256", "HS256"],
            audience="authenticated"
        )
        user_id_str = payload.get("sub")
        if user_id_str:
            return await get_user_by_id(db, uuid.UUID(user_id_str))
    except Exception:
        pass
    return None

# Lista de preguntas rápidas predeterminadas para clientes móviles y web
DEFAULT_QUICK_QUESTIONS = [
    QuickQuestionItem(
        id="q1",
        label="¿Qué es RCM?",
        question="¿Qué es RCM según la norma SAE JA1011 y cuáles son sus 7 preguntas fundamentales?",
        category="metodologia"
    ),
    QuickQuestionItem(
        id="q2",
        label="Vibraciones ISO 10816",
        question="¿Cuáles son los umbrales de severidad de vibración (mm/s RMS) según ISO 10816-3 para maquinaria rotativa?",
        category="diagnostico"
    ),
    QuickQuestionItem(
        id="q3",
        label="Cálculo de Criticidad",
        question="¿Cómo se calcula la criticidad de un activo mediante la matriz de riesgo y cuáles son las dimensiones de consecuencia?",
        category="criticidad"
    ),
    QuickQuestionItem(
        id="q4",
        label="Análisis AMEF / RPN",
        question="¿Cómo se define el Número de Prioridad de Riesgo (RPN/NPR) en un análisis de modos y efectos de falla?",
        category="fmea"
    ),
    QuickQuestionItem(
        id="q5",
        label="Diagnóstico K-201A",
        question="Evalúa el estado técnico, vibración reciente y modos de falla del compresor K-201A.",
        category="equipo"
    ),
    QuickQuestionItem(
        id="q6",
        label="Crear Orden de Trabajo",
        question="Crea una orden de trabajo urgente para el compresor K-201A por vibración alta.",
        category="mantenimiento"
    )
]

@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Enviar consulta conversacional al Asistente IA RCM",
    description="Recibe un mensaje de texto del usuario, inyecta telemetría real de la base de datos si se menciona un activo y genera una respuesta técnica estructurada."
)
async def chat_text(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    optional_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Ruta: POST /api/v1/chatbot/chat
    Acepta un cuerpo JSON estándar con el mensaje, session_id y opcionalmente equipment_id.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere un mensaje de texto para procesar la consulta."
        )

    try:
        user_info = f"{optional_user.first_name} {optional_user.last_name} ({optional_user.role})" if optional_user else None
        user_id = optional_user.id if optional_user else None

        result = await rcm_chatbot_service.process_message(
            message=payload.message.strip(),
            session_id=payload.session_id,
            equipment_id=payload.equipment_id,
            db=db if payload.include_db_context else None,
            current_user_info=user_info,
            current_user_id=user_id
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando la consulta en el asistente IA: {str(e)}"
        )

@router.post(
    "/chat-multimodal",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Enviar consulta con imagen adjunta (Multimodal)",
    description="Permite enviar una fotografía de una placa de equipo, componente dañado (rodamiento, sello) o gráfico de vibración junto a una consulta técnica."
)
async def chat_multimodal(
    message: Optional[str] = Form(default=""),
    session_id: Optional[str] = Form(default=None),
    equipment_id: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
    db: AsyncSession = Depends(get_db),
    optional_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Ruta: POST /api/v1/chatbot/chat-multimodal
    Acepta multipart/form-data con un archivo de imagen (PNG, JPEG, WebP) de hasta 10MB.
    """
    if not message and not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar un mensaje de texto o adjuntar una imagen para el análisis."
        )

    image_bytes = None
    mime_type = None

    if file:
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tipo de archivo no admitido: {file.content_type}. Debe ser una imagen (image/jpeg, image/png, etc.)."
            )
        try:
            image_bytes = await file.read()
            mime_type = file.content_type
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error leyendo el archivo de imagen adjunto: {str(e)}"
            )

    try:
        user_info = f"{optional_user.first_name} {optional_user.last_name} ({optional_user.role})" if optional_user else None
        user_id = optional_user.id if optional_user else None

        result = await rcm_chatbot_service.process_message(
            message=message or "Analiza esta imagen industrial e identifica el activo, falla física o telemetría.",
            session_id=session_id,
            equipment_id=equipment_id,
            image_bytes=image_bytes,
            mime_type=mime_type,
            db=db,
            current_user_info=user_info,
            current_user_id=user_id
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando el análisis multimodal en el asistente IA: {str(e)}"
        )

@router.post(
    "/crear-orden-trabajo",
    response_model=ChatbotActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear Orden de Trabajo desde el Copiloto IA",
    description="Permite al Asistente IA o al usuario con 1 clic generar una Orden de Trabajo física en PostgreSQL vinculada a un activo industrial."
)
async def crear_orden_trabajo_desde_chat(
    payload: CreateWorkOrderFromChatRequest,
    db: AsyncSession = Depends(get_db),
    optional_user: Optional[User] = Depends(get_optional_current_user)
):
    target = payload.equipment_tag or payload.equipment_id
    if not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe indicar el TAG o UUID del activo industrial."
        )

    res = await rcm_chatbot_service.create_work_order_from_chat(
        db=db,
        title=payload.title,
        equipment_id_or_tag=target,
        priority=payload.priority,
        technician_notes=payload.technician_notes,
        scheduled_for=payload.scheduled_for,
        current_user_id=optional_user.id if optional_user else None
    )

    if not res.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("error", "Error creando orden de trabajo.")
        )

    return ChatbotActionResponse(
        success=True,
        message=f"Orden de trabajo '{res['work_order_id']}' creada exitosamente para activo {res['equipment_tag']}.",
        created_id=res["work_order_id"],
        entity_type="work_order",
        data=res
    )

@router.post(
    "/crear-plan",
    response_model=ChatbotActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear Plan de Mantenimiento desde el Copiloto IA",
    description="Genera un nuevo Plan de Mantenimiento (Preventivo / Predictivo) directamente en PostgreSQL."
)
async def crear_plan_desde_chat(
    payload: CreateMaintenancePlanFromChatRequest,
    db: AsyncSession = Depends(get_db),
    optional_user: Optional[User] = Depends(get_optional_current_user)
):
    target = payload.equipment_tag or payload.equipment_id
    if not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe indicar el TAG o UUID del activo industrial."
        )

    res = await rcm_chatbot_service.create_maintenance_plan_from_chat(
        db=db,
        title=payload.title,
        equipment_id_or_tag=target,
        maintenance_type=payload.maintenance_type,
        frequency_days=payload.frequency_days or 30,
        description=payload.description,
        current_user_id=optional_user.id if optional_user else None
    )

    if not res.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("error", "Error creando plan de mantenimiento.")
        )

    return ChatbotActionResponse(
        success=True,
        message=f"Plan de mantenimiento '{res['maintenance_id']}' creado exitosamente para activo {res['equipment_tag']}.",
        created_id=res["maintenance_id"],
        entity_type="maintenance_plan",
        data=res
    )

@router.get(
    "/history/{session_id}",
    response_model=ChatHistoryResponse,
    summary="Obtener historial de conversación",
    description="Recupera la lista de turnos (mensajes de usuario y asistente) de una sesión activa."
)
async def get_history(session_id: str):
    history_raw = rcm_chatbot_service.get_history(session_id)
    history_items = [
        ChatMessage(role=m.get("role", "usuario"), content=m.get("content", ""))
        for m in history_raw
    ]
    return {
        "success": True,
        "session_id": session_id,
        "history": history_items
    }

@router.post(
    "/clear",
    response_model=ChatClearResponse,
    summary="Limpiar historial de sesión",
    description="Elimina la memoria conversacional de la sesión especificada para reiniciar el contexto."
)
async def clear_history(payload: ChatClearRequest):
    rcm_chatbot_service.clear_history(payload.session_id)
    return {
        "success": True,
        "message": f"Historial de la sesión '{payload.session_id}' eliminado correctamente."
    }

@router.get(
    "/quick-questions",
    response_model=List[QuickQuestionItem],
    summary="Obtener preguntas rápidas recomendadas",
    description="Retorna una lista de consultas técnicas estándar sobre RCM, ISO 10816, AMEF y equipos para facilitar la interacción en la interfaz móvil o web."
)
async def get_quick_questions():
    return DEFAULT_QUICK_QUESTIONS
