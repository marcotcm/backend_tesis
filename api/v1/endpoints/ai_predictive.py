import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

# Ajustes de dependencias del proyecto
from core.security import get_current_user
from db.session import get_db
from models.user import User
from services.ai_predictive_service import (
    ejecutar_analisis_predictivo_ia,
    ejecutar_analisis_predictivo_fallback,
    generar_plan_mantenimiento_ia,
    generar_plan_mantenimiento_fallback,
    evaluar_riesgo_global_planta,
    generar_planes_mantenimiento_globales,
    obtener_estado_gemelo_digital,
    actualizar_topologia_gemelo_digital,
    simular_escenario_gemelo_digital,
    aplicar_consigna_scada_equipo,
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


class TopologiaNodoItem(BaseModel):
    equipment_id: uuid.UUID
    stage: Optional[str] = None
    pid_position: Optional[dict] = None
    pid_connections: Optional[List[dict]] = None


class ActualizarTopologiaRequest(BaseModel):
    nodes: List[TopologiaNodoItem] = Field(..., min_length=1)


class SimulacionOverrideItem(BaseModel):
    equipment_id: uuid.UUID
    vibration_mm_s: Optional[float] = Field(default=None, ge=0, le=50)
    temperature_celsius: Optional[float] = Field(default=None, ge=-50, le=500)
    pressure_psi: Optional[float] = Field(default=None, ge=0, le=10000)
    flow_rate: Optional[float] = Field(default=None, ge=0)
    motor_amps: Optional[float] = Field(default=None, ge=0)
    valve_open_pct: Optional[float] = Field(default=None, ge=0, le=100)
    operational_status: Optional[str] = None


class SimularGemeloRequest(BaseModel):
    taxonomy_id: Optional[uuid.UUID] = None
    overrides: List[SimulacionOverrideItem] = Field(default_factory=list)


class ConsignaScadaRequest(BaseModel):
    valve_open_pct: Optional[float] = Field(default=None, ge=0, le=100)
    rpm_setpoint: Optional[float] = Field(default=None, ge=0, le=20000)
    pressure_setpoint_psi: Optional[float] = Field(default=None, ge=0, le=10000)
    mode: Optional[str] = Field(default=None)
    edge_webhook_url: Optional[str] = Field(default=None)


# =====================================================================
# RUTAS INDIVIDUALES (CON NOTIFICACIÓN AL USUARIO EN SESIÓN)
# =====================================================================

@router.post(
    "/analizar-equipo/{equipment_id}",
    status_code=status.HTTP_200_OK,
    summary="Ejecutar análisis predictivo manual por IA",
    description="Analiza el historial, métricas, fallas, mantenimientos y criticidad de un equipo. Envía notificación siempre y guarda recomendación si existe probabilidad de falla."
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
        trigger_reference_id=None,
        user_id=current_user.id
    )
    
    if resultado.get("error") and "Equipo no encontrado" in str(resultado.get("error")):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Equipo no encontrado en la base de datos."
        )
        
    if resultado.get("error"):
        resultado = await ejecutar_analisis_predictivo_fallback(
            db=db,
            equipment_id=equipment_id,
            trigger_source=origen_disparo,
            trigger_reference_id=None,
            user_id=current_user.id
        )
        if resultado.get("error"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Error durante el análisis de IA: {resultado['error']}"
            )

    mensaje_respuesta = (
        "Análisis predictivo ejecutado con éxito. Se detectó riesgo y se guardó la recomendación."
        if resultado.get("recomendacion_generada")
        else "Análisis predictivo ejecutado con éxito. El equipo opera normal sin riesgo de falla."
    )

    return {
        "mensaje": mensaje_respuesta,
        "resultado": resultado
    }


@router.post(
    "/generar-plan/{equipment_id}",
    status_code=status.HTTP_200_OK,
    summary="Generar plan de mantenimiento estructurado por IA",
    description="Toma un diagnóstico previo y diseña un plan prescriptivo detallado (tareas, repuestos, seguridad). El plan SIEMPRE se guarda como una recomendación pendiente de auditoría."
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
        trigger_source=origen_disparo,
        user_id=current_user.id
    )
    
    if resultado.get("error") and "Equipo no encontrado" in str(resultado.get("error")):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Equipo no encontrado en la base de datos."
        )

    if resultado.get("error"):
        resultado = await generar_plan_mantenimiento_fallback(
            db=db,
            equipment_id=equipment_id,
            contexto_diagnostico=request.contexto_diagnostico,
            trigger_source=origen_disparo,
            user_id=current_user.id
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
# RUTAS EXPLÍCITAS DE CONTINGENCIA
# =====================================================================

@router.post(
    "/analizar-equipo-contingencia/{equipment_id}",
    status_code=status.HTTP_200_OK,
    summary="Ejecutar análisis predictivo de contingencia con los mismos datos reales",
    description="Ruta de respaldo para cuando la IA falla. Toma las mismas métricas, fallas, mantenimientos y predicción ML del equipo."
)
async def analizar_equipo_contingencia(
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    origen_disparo = f"Análisis Predictivo (Contingencia) Solicitado por: {current_user.email}"

    resultado = await ejecutar_analisis_predictivo_fallback(
        db=db,
        equipment_id=equipment_id,
        trigger_source=origen_disparo,
        trigger_reference_id=None,
        user_id=current_user.id
    )

    if resultado.get("error") and "Equipo no encontrado" in str(resultado.get("error")):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Equipo no encontrado en la base de datos."
        )

    if resultado.get("error"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error durante el análisis de contingencia: {resultado['error']}"
        )

    return {
        "mensaje": "Análisis de contingencia ejecutado con éxito.",
        "resultado": resultado
    }


@router.post(
    "/generar-plan-contingencia/{equipment_id}",
    status_code=status.HTTP_200_OK,
    summary="Generar plan de mantenimiento de contingencia con los mismos datos reales",
    description="Ruta de respaldo para cuando la IA falla. Diseña el plan con los mismos datos reales del equipo y siempre lo guarda."
)
async def generar_plan_contingencia(
    equipment_id: uuid.UUID,
    request: GenerarPlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    origen_disparo = f"Generación de Plan (Contingencia) Solicitada por: {current_user.email}"

    resultado = await generar_plan_mantenimiento_fallback(
        db=db,
        equipment_id=equipment_id,
        contexto_diagnostico=request.contexto_diagnostico,
        trigger_source=origen_disparo,
        user_id=current_user.id
    )

    if resultado.get("error") and "Equipo no encontrado" in str(resultado.get("error")):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Equipo no encontrado en la base de datos."
        )

    if resultado.get("error"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Fallo en la estructuración del plan de contingencia: {resultado['error']}"
        )

    return {
        "mensaje": "Plan de mantenimiento de contingencia generado y enviado a bandeja de auditoría.",
        "resultado": resultado
    }


# =====================================================================
# RUTAS GLOBALES (NIVEL PLANTA)
# =====================================================================

@router.get(
    "/gemelo-digital",
    status_code=status.HTTP_200_OK,
    summary="Estado en tiempo real del Gemelo Digital (Telemetría + Topología + Pronóstico)",
    description="Devuelve todos los activos activos con su última telemetría, deltas, predicción de riesgo, criticidad, órdenes activas, coordenadas P&ID y enlaces."
)
async def consultar_gemelo_digital(
    taxonomy_id: Optional[uuid.UUID] = Query(None, description="Filtrar por categoría de taxonomía"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resultado = await obtener_estado_gemelo_digital(db=db, taxonomy_id=taxonomy_id)
    return {
        "mensaje": "Estado del Gemelo Digital sincronizado en tiempo real.",
        "resultado": resultado
    }


@router.put(
    "/gemelo-digital/topologia",
    status_code=status.HTTP_200_OK,
    summary="Guardar topología P&ID personalizada (coordenadas y enlaces nodo-a-nodo)"
)
async def actualizar_topologia_pid(
    payload: ActualizarTopologiaRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resultado = await actualizar_topologia_gemelo_digital(
        db=db,
        nodes_layout=[n.model_dump() for n in payload.nodes],
        user_id=current_user.id,
    )
    return {
        "mensaje": f"Topología P&ID actualizada en {resultado['updated_count']} activos.",
        "resultado": resultado,
    }


@router.post(
    "/gemelo-digital/simular",
    status_code=status.HTTP_200_OK,
    summary="Simulador What-If en cascada (no destructivo)"
)
async def simular_gemelo_digital(
    payload: SimularGemeloRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resultado = await simular_escenario_gemelo_digital(
        db=db,
        overrides=[ov.model_dump() for ov in payload.overrides],
        taxonomy_id=payload.taxonomy_id,
    )
    return {
        "mensaje": "Escenario What-If calculado en memoria sin modificar datos históricos.",
        "resultado": resultado,
    }


@router.post(
    "/gemelo-digital/consigna/{equipment_id}",
    status_code=status.HTTP_200_OK,
    summary="Emitir consigna operativa SCADA (válvula, RPM, presión, modo AUTO/MANUAL)"
)
async def enviar_consigna_scada(
    equipment_id: uuid.UUID,
    payload: ConsignaScadaRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resultado = await aplicar_consigna_scada_equipo(
        db=db,
        equipment_id=equipment_id,
        consigna=payload.model_dump(exclude_unset=True),
        current_user=current_user,
    )
    return {
        "mensaje": f"Consigna SCADA aplicada en {resultado['tag_number']}.",
        "resultado": resultado,
    }


@router.get(
    "/riesgo-planta",
    status_code=status.HTTP_200_OK,
    summary="Análisis de riesgo global (Radar Predictivo ML)",
    description="Escanea toda la maquinaria activa usando el modelo estadístico XGBoost para identificar equipos próximos a fallar."
)
async def analizar_riesgo_planta(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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
    origen_disparo = f"Generación Masiva de Planes Solicitada por: {current_user.email}"
    
    resultado = await generar_planes_mantenimiento_globales(
        db=db,
        trigger_source=origen_disparo,
        user_id=current_user.id
    )
    
    if resultado["planes_creados"] == 0 and len(resultado.get("errores", [])) > 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Se encontraron equipos en riesgo, pero falló la generación de los planes en todos los casos."
        )

    return {
        "mensaje": f"Se han generado {resultado['planes_creados']} planes de mantenimiento para equipos en alerta.",
        "resultado": resultado
    }