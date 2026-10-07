import os
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from google import genai
from google.genai import types

from models.equipment import Equipment
from models.equipment_metrics import EquipmentMetricHistory
from models.failure_history import FailureHistory
from models.maintenance_history import MaintenanceHistory
from models.equipment_criticality import EquipmentCriticality
from crud import ai_recommendation as crud_recommendation

# Inicializar cliente de la API de Gemini
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

async def ejecutar_analisis_predictivo_ia(
    db: AsyncSession, 
    equipment_id: uuid.UUID, 
    trigger_source: str, 
    trigger_reference_id: uuid.UUID | None = None
):
    """
    Servicio central que recopila contexto histórico (últimos 7 días), 
    métricas, criticidad, fallas y mantenimientos, y consulta a Gemini 
    para evaluar riesgo a 7 días y registrar la recomendación si aplica.
    """
    # 1. Obtener el equipo y sus especificaciones (standard_metric)
    eq_result = await db.execute(select(Equipment).where(Equipment.id == equipment_id))
    equipment = eq_result.scalar_one_or_none()
    if not equipment:
        return None

    # 2. Obtener criticidad del equipo
    crit_result = await db.execute(select(EquipmentCriticality).where(EquipmentCriticality.equipment_id == equipment_id))
    criticality = crit_result.scalar_one_or_none()

    # 3. Obtener métricas de los últimos 7 días
    hace_7_dias = datetime.now(timezone.utc) - timedelta(days=7)
    metrics_result = await db.execute(
        select(EquipmentMetricHistory)
        .where(and_(EquipmentMetricHistory.equipment_id == equipment_id, EquipmentMetricHistory.recorded_at >= hace_7_dias))
        .order_by(EquipmentMetricHistory.recorded_at.desc())
    )
    metricas_recientes = metrics_result.scalars().all()

    # 4. Obtener historial de fallas recientes del equipo
    failures_result = await db.execute(
        select(FailureHistory)
        .where(FailureHistory.equipment_id == equipment_id)
        .order_by(FailureHistory.failure_date.desc())
        .limit(5)
    )
    ultimas_fallas = failures_result.scalars().all()

    # 5. Obtener historial de mantenimientos recientes
    maint_result = await db.execute(
        select(MaintenanceHistory)
        .where(MaintenanceHistory.equipment_id == equipment_id)
        .order_by(MaintenanceHistory.execution_date.desc())
        .limit(5)
    )
    ultimos_mantenimientos = maint_result.scalars().all()

    # 6. Construir el contexto unificado en texto para la IA
    specs = equipment.technical_specifications or {}
    standard_metric = specs.get("standard_metric", {})

    contexto_tecnico = (
        f"ACTIVO A EVALUAR:\n"
        f"- Tag: {equipment.tag_number} | Nombre: {equipment.name} | Tipo: {equipment.equipment_type}\n"
        f"- Umbrales estándar permitidos (standard_metric): {standard_metric}\n"
        f"- Nivel de Criticidad: {criticality.criticality_level if criticality else 'No evaluado'} (RPN: {criticality.rpn_score if criticality else 'N/D'})\n\n"
        f"HISTORIAL DE MÉTRICAS (Últimos 7 días):\n" + 
        "\n".join([f"  * Fecha: {m.recorded_at} | Temp: {m.temperature_celsius}°C | Vib: {m.vibration_mm_s} mm/s | Notas: {m.notes}" for m in metricas_recientes]) + "\n\n"
        f"HISTORIAL DE FALLAS PREVIAS:\n" + 
        "\n".join([f"  * Fecha: {f.failure_date} | Modo: {f.failure_mode} | Severidad: {f.severity} | Desc: {f.description}" for f in ultimas_fallas]) + "\n\n"
        f"HISTORIAL DE MANTENIMIENTOS RECIENTES:\n" + 
        "\n".join([f"  * Fecha: {m.execution_date} | Acción: {m.action_taken}" for m in ultimos_mantenimientos])
    )

    # 7. Definir función local (Tool) que Gemini invocará automáticamente si detecta riesgo a 7 días
    def registrar_recomendacion_bd(confianza: float, prediction_type: str, recomendacion_texto: str) -> str:
        """Registra la recomendación analizada en la tabla ai_recommendations de la base de datos."""
        return "Guardado exitoso"

    # 8. Configurar Prompt y Reglas estrictas con Gemini
    configuracion = types.GenerateContentConfig(
        system_instruction=(
            "Eres un ingeniero jefe de confiabilidad industrial experto en análisis predictivo (RCM). "
            "Tu labor es analizar el comportamiento de las métricas de los últimos 7 días frente a los umbrales permitidos, "
            "correlacionándolo con el historial de fallas y mantenimientos.\n\n"
            "REGLAS ESTRICTAS:\n"
            "1. Determina si el equipo muestra tendencias claras o anomalías que indiquen una alta propensión a fallar en un horizonte de alrededor de 7 días.\n"
            "2. Si y solo si existe un riesgo inminente de fallo en los próximos 7 días, debes redactar una recomendación técnica "
            "y ejecutar la función de guardado pasando un puntaje de confianza (0-100), el tipo de predicción ('Alerta de Falla Inminente' o 'Ajuste de Frecuencia') "
            "y el texto detallado de la recomendación.\n"
            "3. Si el equipo opera de manera estable dentro de sus rangos normales, no ejecutes ninguna función y explica brevemente por qué el equipo está estable."
        ),
        tools=[registrar_recomendacion_bd],
        temperature=0.2,
    )

    respuesta = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contexto_tecnico,
        config=configuracion
    )

    # 9. Procesar la llamada a la función si la IA decidió guardar la recomendación
    recomendacion_creada = None
    if respuesta.function_calls:
        for llamada in respuesta.function_calls:
            if llamada.name == "registrar_recomendacion_bd":
                args = llamada.args
                payload_db = {
                    "equipment_id": equipment_id,
                    "trigger_source": trigger_source,
                    "trigger_reference_id": trigger_reference_id,
                    "recommendation_text": args.get("recomendacion_texto"),
                    "confidence_score": args.get("confianza"),
                    "prediction_type": args.get("prediction_type"),
                    "status": "Pendiente"
                }
                recomendacion_creada = await crud_recommendation.create(db, payload_db)

    return {
        "analisis_ia": respuesta.text,
        "recomendacion_generada": recomendacion_creada is not None,
        "detalle_recomendacion": recomendacion_creada
    }