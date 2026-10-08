import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

# Ajusta estos imports según la estructura real de tus carpetas
from core.security import get_current_user
from db.session import get_db
from models.user import User
from services.ai_predictive_service import (
    ejecutar_analisis_predictivo_ia,
    generar_plan_mantenimiento_ia
)

router = APIRouter()

# =====================================================================
# ESQUEMAS DE ENTRADA (REQUEST BODY)
# =====================================================================
class GenerarPlanRequest(BaseModel):
    contexto_diagnostico: str = Field(
        ..., 
        description="Diagnóstico predictivo previo o contexto técnico manual para que la IA diseñe el plan de mantenimiento."
    )


# =====================================================================
# RUTAS (ENDPOINTS)
# =====================================================================

@router.post(
    "/analizar-equipo/{equipment_id}",
    status_code=status.HTTP_200_OK,
    summary="Ejecutar análisis predictivo manual por IA",
    description="Analiza el historial de 7 días, métricas, fallas, mantenimientos y criticidad de un equipo para generar recomendaciones si hay riesgo inminente."
)
async def analizar_equipo_manual(
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** POST /api/v1/ai-predictivo/analizar-equipo/{equipment_id}
    * **Uso:** Dispara el análisis experto de Gemini de forma manual para un equipo específico.
    """
    origen_disparo = f"Análisis Manual Solicitado por: {current_user.email}"

    resultado = await ejecutar_analisis_predictivo_ia(
        db=db,
        equipment_id=equipment_id,
        trigger_source=origen_disparo,
        trigger_reference_id=None
    )
    
    if resultado.get("error") and "Equipo no encontrado" in str(resultado.get("error")):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Equipo no encontrado en la base de datos."
        )
        
    if resultado.get("error"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Error durante el análisis de IA: {resultado['error']}"
        )

    return {
        "mensaje": "Análisis predictivo ejecutado con éxito.",
        "resultado": resultado
    }


@router.post(
    "/generar-plan/{equipment_id}",
    status_code=status.HTTP_200_OK,
    summary="Generar plan de mantenimiento estructurado por IA",
    description="Toma un diagnóstico previo y diseña un plan prescriptivo detallado (tareas, repuestos, seguridad). El plan se guarda como una recomendación pendiente de auditoría."
)
async def generar_plan_manual(
    equipment_id: uuid.UUID,
    request: GenerarPlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** POST /api/v1/ai-predictivo/generar-plan/{equipment_id}
    * **Uso:** Construye el contrato JSON exacto del MaintenancePlan y lo guarda para auditoría.
    """
    origen_disparo = f"Generación de Plan Solicitada por: {current_user.email}"

    resultado = await generar_plan_mantenimiento_ia(
        db=db,
        equipment_id=equipment_id,
        contexto_diagnostico=request.contexto_diagnostico,
        trigger_source=origen_disparo
    )
    
    if resultado.get("error") and "Equipo no encontrado" in str(resultado.get("error")):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Equipo no encontrado en la base de datos."
        )

    if resultado.get("error"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Fallo en la estructuración del plan: {resultado['error']}"
        )

    return {
        "mensaje": "Plan de mantenimiento generado y enviado a bandeja de auditoría.",
        "resultado": resultado
    }