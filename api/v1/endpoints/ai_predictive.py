import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from db.session import get_db
from models.user import User
from services.ai_predictive_service import ejecutar_analisis_predictivo_ia

router = APIRouter()

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
    resultado = await ejecutar_analisis_predictivo_ia(
        db=db,
        equipment_id=equipment_id,
        trigger_source="Análisis Manual Solicitado por Usuario",
        trigger_reference_id=None
    )
    
    if not resultado:
        return {"error": "Equipo no encontrado"}

    return {
        "mensaje": "Análisis predictivo ejecutado con éxito.",
        "resultado": resultado
    }