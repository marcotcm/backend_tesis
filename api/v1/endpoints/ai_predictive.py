import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

# Ajustes de dependencias del proyecto
from core.security import get_current_user
from db.session import get_db
from models.user import User
from services.ai_predictive_service import (
    ejecutar_analisis_predictivo_ia,
    generar_plan_mantenimiento_ia,
    evaluar_riesgo_global_planta,
    generar_planes_mantenimiento_globales
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
# RUTAS INDIVIDUALES (LAS QUE YA TENÍAS)
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


# =====================================================================
# NUEVAS RUTAS GLOBALES (NIVEL PLANTA)
# =====================================================================

@router.get(
    "/riesgo-planta",
    status_code=status.HTTP_200_OK,
    summary="Análisis de riesgo global (Radar Predictivo ML)",
    description="Escanea toda la maquinaria activa usando el modelo estadístico XGBoost para identificar equipos próximos a fallar. Alta velocidad, no consume cuota generativa."
)
async def analizar_riesgo_planta(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/ai-predictivo/riesgo-planta
    * **Uso:** Obtiene el listado de máquinas ordenadas por probabilidad estadística de falla inminente.
    """
    resultado = await evaluar_riesgo_global_planta(db=db)
    return {
        "mensaje": "Análisis de riesgo global ejecutado con éxito.",
        "resultado": resultado
    }


@router.post(
    "/planes-planta",
    status_code=status.HTTP_200_OK,
    summary="Generar planes en lote para equipos en riesgo",
    description="Filtra las máquinas en riesgo usando Machine Learning y delega a la IA generativa la creación de un plan de mantenimiento preventivo para cada una."
)
async def generar_planes_planta(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** POST /api/v1/ai-predictivo/planes-planta
    * **Uso:** Operación en lote (Batch) que automatiza la planificación táctica de mantenimiento para activos críticos detectados por ML.
    """
    origen_disparo = f"Generación Masiva de Planes Solicitada por: {current_user.email}"
    
    resultado = await generar_planes_mantenimiento_globales(
        db=db,
        trigger_source=origen_disparo
    )
    
    # Manejo de error en caso de que el escaneo falle en generar la pauta para todos los detectados
    if resultado["planes_creados"] == 0 and len(resultado.get("errores", [])) > 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Se encontraron equipos en riesgo, pero falló la generación de los planes en todos los casos."
        )

    return {
        "mensaje": f"Se han generado {resultado['planes_creados']} planes de mantenimiento para equipos en alerta.",
        "resultado": resultado
    }