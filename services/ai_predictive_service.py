import os
import uuid
from typing import Literal, List, Optional
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field, ValidationError

from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError

# Importaciones de tus modelos de Heimdall RCM
from models.equipment import Equipment
from models.equipment_metrics import EquipmentMetricHistory
from models.failure_history import FailureHistory
from models.maintenance_history import MaintenanceHistory
from models.equipment_criticality import EquipmentCriticality
from crud import ai_recommendation as crud_recommendation
from dotenv import load_dotenv

load_dotenv()

# Inicialización del cliente con el nuevo SDK
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# =====================================================================
# 1. ESQUEMAS PARA LA FUNCIÓN 1: ANÁLISIS PREDICTIVO RCM
# =====================================================================
class InformeConfiabilidadRCM(BaseModel):
    requiere_intervencion: bool = Field(
        description="True si se detecta una anomalía o desviación. False si los parámetros operan bajo control estadístico."
    )
    prediction_type: Literal[
        'Alerta Crítica de Falla Inminente', 
        'Ajuste de Frecuencia de Monitoreo',
        'Sustitución Preventiva Recomendada',
        'Inspección Basada en Condición (CBM)',
        'Operación Normal'
    ]
    confianza: float = Field(description="Nivel de confianza del diagnóstico (0.0 a 1.0)")
    diagnostico_principal: str = Field(description="Resumen corto del estado del activo")
    evaluacion_condicion: str = Field(description="Análisis detallado de métricas (vibración, temperatura) y correlación con el historial FMEA")
    hipotesis_causa_raiz: str = Field(description="Explicación técnica de la causa subyacente de la degradación")
    normas_aplicadas: List[str] = Field(description="Lista de normas y principios aplicados (ej. ISO 20816-3, SAE JA1011)")
    plan_accion: List[str] = Field(description="Lista de pasos concretos a seguir para mantenimiento o monitoreo")

# =====================================================================
# 2. ESQUEMAS PARA LA FUNCIÓN 2: GENERACIÓN DE PLANES DE MANTENIMIENTO
# =====================================================================
class RepuestoSchema(BaseModel):
    name: str = Field(description="Nombre del repuesto o insumo")
    reference: str = Field(description="Número de parte o referencia técnica")
    quantity: int = Field(description="Cantidad requerida")

class TareaMantenimientoSchema(BaseModel):
    title: str = Field(description="Título descriptivo de la tarea")
    description: str = Field(description="Descripción técnica de lo que se va a realizar")
    category: Literal["inspection", "lubrication", "replacement", "calibration", "cleaning"]
    estimated_duration_minutes: int
    assigned_roles: List[str] = Field(description="Ej: ['senior_technician', 'field_technician']")
    required_tools: List[str] = Field(description="Herramientas necesarias (ej. Torquímetro, Calibrador)")
    required_parts: List[RepuestoSchema]
    instructions: List[str] = Field(description="Paso a paso técnico de ejecución")
    safety_precautions: List[str] = Field(description="Medidas de seguridad (LOTO, H2S, etc.)")

class CronogramaSchema(BaseModel):
    start_date: str = Field(description="Fecha de inicio en formato ISO 8601 (ej. 2026-10-15T08:00:00Z)")
    end_date: str = Field(description="Fecha de fin en formato ISO 8601")
    intervals_days: int

class PlanMantenimientoIA(BaseModel):
    title: str = Field(description="Título formal del plan")
    maintenance_type: str = Field(description="Ej: Adaptativo (IA), Preventivo, Predictivo")
    description: str = Field(description="Justificación técnica del plan")
    frequency_days: int
    priority: Literal["low", "medium", "high", "critical"]
    estimated_hours: float
    schedule: CronogramaSchema
    tasks: List[TareaMantenimientoSchema]

# =====================================================================
# FUNCIÓN 1: ANÁLISIS PREDICTIVO (FORMATO PROFESIONAL)
# =====================================================================
async def ejecutar_analisis_predictivo_ia(
    db: AsyncSession, 
    equipment_id: uuid.UUID, 
    trigger_source: str, 
    trigger_reference_id: uuid.UUID | None = None
) -> dict:
    
    equipment = (await db.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one_or_none()
    if not equipment:
        return {"analisis_ia": None, "error": "Equipo no encontrado", "recomendacion_generada": False}

    criticality = (await db.execute(select(EquipmentCriticality).where(EquipmentCriticality.equipment_id == equipment_id))).scalar_one_or_none()
    hace_7_dias = datetime.now(timezone.utc) - timedelta(days=7)
    
    metricas_recientes = (await db.execute(
        select(EquipmentMetricHistory)
        .where(and_(EquipmentMetricHistory.equipment_id == equipment_id, EquipmentMetricHistory.recorded_at >= hace_7_dias))
        .order_by(EquipmentMetricHistory.recorded_at.desc())
    )).scalars().all()

    ultimas_fallas = (await db.execute(
        select(FailureHistory).where(FailureHistory.equipment_id == equipment_id).order_by(FailureHistory.failure_date.desc()).limit(5)
    )).scalars().all()

    ultimos_mantenimientos = (await db.execute(
        select(MaintenanceHistory).where(MaintenanceHistory.equipment_id == equipment_id).order_by(MaintenanceHistory.execution_date.desc()).limit(5)
    )).scalars().all()

    str_metricas = "\n".join([f"  * {m.recorded_at} | Temp: {m.temperature_celsius}°C | Vib: {m.vibration_mm_s} mm/s | Notas: {m.notes}" for m in metricas_recientes])
    str_fallas = "\n".join([f"  * {f.failure_date} | Modo: {f.failure_mode} | Severidad: {f.severity} | Desc: {f.description}" for f in ultimas_fallas])
    str_mantenimientos = "\n".join([f"  * {m.execution_date} | Acción ejecutada: {m.action_taken}" for m in ultimos_mantenimientos])

    contexto_tecnico = (
        f"PERFIL DEL ACTIVO:\n"
        f"- Tag: {equipment.tag_number} | Nombre: {equipment.name} | Tipo: {equipment.equipment_type}\n"
        f"- Análisis de Criticidad: Nivel {criticality.criticality_level if criticality else 'No evaluado'} | RPN: {criticality.rpn_score if criticality else 'N/D'}\n\n"
        f"METRÍAS DE CONDICIÓN (CBM - Últimos 7 días):\n{str_metricas}\n\n"
        f"HISTORIAL DE MODOS DE FALLA (FMEA):\n{str_fallas}\n\n"
        f"HISTORIAL DE INTERVENCIONES:\n{str_mantenimientos}"
    )

    instrucciones_rcm = (
        "Eres un Ingeniero Jefe de Confiabilidad CMRP, experto en Mantenimiento Centrado en Confiabilidad (SAE JA1011) y Gestión de Activos (ISO 55000).\n"
        "Evalúa la salud del activo basándote en los datos. Si hay anomalías graves, genera un plan de acción estricto."
    )

    configuracion = types.GenerateContentConfig(
        system_instruction=instrucciones_rcm,
        temperature=0.1, 
        response_mime_type="application/json",
        response_schema=InformeConfiabilidadRCM,
    )

    try:
        respuesta = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite", 
            contents=contexto_tecnico,
            config=configuracion
        )
        resultado_obj = InformeConfiabilidadRCM.model_validate_json(respuesta.text)
        resultado_dict = resultado_obj.model_dump()
        
    except Exception as e:
        print(f"[ERROR IA] Fallo en análisis predictivo: {e}")
        return {"analisis_ia": None, "error": str(e), "recomendacion_generada": False}

    recomendacion_creada = None
    
    if resultado_obj.requiere_intervencion:
        normas_str = "\n* ".join(resultado_obj.normas_aplicadas)
        plan_accion_str = "\n".join([f"{i}. {accion}" for i, accion in enumerate(resultado_obj.plan_accion, start=1)])

        # TEXTO PLANO PROFESIONAL
        informe_texto = (
            f"INFORME DE CONFIABILIDAD Y DIAGNÓSTICO TÉCNICO (CMRP / ISO 55000)\n"
            f"=================================================================\n\n"
            f"DIAGNÓSTICO: {resultado_obj.diagnostico_principal.upper()}\n"
            f"Nivel de Confianza: {int(resultado_obj.confianza * 100)}%\n\n"
            f"1. EVALUACIÓN DE CONDICIÓN Y CORRELACIÓN FMEA\n"
            f"---------------------------------------------\n"
            f"{resultado_obj.evaluacion_condicion}\n\n"
            f"2. HIPÓTESIS DE CAUSA RAÍZ\n"
            f"--------------------------\n"
            f"{resultado_obj.hipotesis_causa_raiz}\n\n"
            f"3. NORMAS Y PRINCIPIOS APLICADOS\n"
            f"--------------------------------\n"
            f"* {normas_str}\n\n"
            f"4. PLAN DE ACCIÓN INMEDIATO PARA PLANIFICACIÓN\n"
            f"----------------------------------------------\n"
            f"{plan_accion_str}\n"
        )
        
        payload_db = {
            "equipment_id": equipment_id,
            "trigger_source": trigger_source,
            "trigger_reference_id": trigger_reference_id,
            "recommendation_text": informe_texto,
            "confidence_score": float(resultado_obj.confianza),
            "prediction_type": resultado_obj.prediction_type,
            "status": "Pendiente"
        }
        
        recomendacion_creada = await crud_recommendation.create(db, payload_db)

    return {
        "analisis_ia": resultado_dict, 
        "recomendacion_generada": recomendacion_creada is not None,
        "detalle_recomendacion": recomendacion_creada
    }

# =====================================================================
# FUNCIÓN 2: GENERACIÓN DE PLAN DE MANTENIMIENTO IA (RCM / API)
# =====================================================================
async def generar_plan_mantenimiento_ia(
    db: AsyncSession, 
    equipment_id: uuid.UUID,
    contexto_diagnostico: str,
    trigger_source: str = "Asistente IA - Generación de Plan"
) -> dict:
    
    equipment = (await db.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one_or_none()
    if not equipment:
        return {"plan_generado": None, "error": "Equipo no encontrado", "recomendacion_generada": False}

    instrucciones_planificador = (
        "Eres un Planificador Senior de Mantenimiento Industrial. Tu tarea es diseñar un Plan de Mantenimiento "
        "detallado y prescriptivo para un equipo industrial, basándote en el contexto o diagnóstico proporcionado.\n\n"
        "REGLAS:\n"
        "1. Especifica repuestos realistas (códigos técnicos, normas API/ISO si aplica).\n"
        "2. Detalla herramientas específicas requeridas (ej. 'Torquímetro 1/2 pulg 50-250 ft-lb', no solo 'Herramientas').\n"
        "3. Incluye precauciones de seguridad rigurosas (LOTO, H2S, trabajos en caliente, etc.).\n"
        "4. Calcula horas estimadas de forma realista según la suma de las tareas.\n"
        "5. Las fechas (start_date, end_date) deben estar en formato ISO 8601 (Z)."
    )

    datos_entrada = (
        f"Datos del Equipo:\n"
        f"- Tag: {equipment.tag_number}\n"
        f"- Nombre: {equipment.name}\n"
        f"- Tipo: {equipment.equipment_type}\n\n"
        f"Contexto o Diagnóstico para generar el plan:\n"
        f"{contexto_diagnostico}"
    )

    configuracion = types.GenerateContentConfig(
        system_instruction=instrucciones_planificador,
        temperature=0.2, 
        response_mime_type="application/json",
        response_schema=PlanMantenimientoIA,
    )

    try:
        respuesta = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=datos_entrada,
            config=configuracion
        )
        
        plan_obj = PlanMantenimientoIA.model_validate_json(respuesta.text)
        plan_dict = plan_obj.model_dump()
        
    except ValidationError as e:
        print(f"[ERROR PYDANTIC] Fallo en el contrato del plan: {e}")
        return {"plan_generado": None, "error": "Fallo en validación de esquema JSON", "recomendacion_generada": False}
    except Exception as e:
        print(f"[ERROR IA] Fallo generando plan: {e}")
        return {"plan_generado": None, "error": str(e), "recomendacion_generada": False}

    # TRANSFORMACIÓN DEL JSON A TEXTO PLANO PROFESIONAL PARA LA BITÁCORA
    texto_plan = (
        f"PROPUESTA DE PLAN DE MANTENIMIENTO: {plan_obj.title.upper()}\n"
        f"=================================================================\n\n"
        f"TIPO DE PLAN: {plan_obj.maintenance_type} | PRIORIDAD: {plan_obj.priority.upper()}\n"
        f"FRECUENCIA: {plan_obj.frequency_days} días | DURACIÓN ESTIMADA: {plan_obj.estimated_hours} hrs\n\n"
        f"JUSTIFICACIÓN TÉCNICA Y CONTEXTO:\n"
        f"---------------------------------\n"
        f"{plan_obj.description}\n\n"
        f"DESGLOSE DE TAREAS PRINCIPALES:\n"
        f"-------------------------------\n"
    )

    for i, tarea in enumerate(plan_obj.tasks, start=1):
        repuestos_str = ", ".join([p.name for p in tarea.required_parts]) if tarea.required_parts else "Ninguno requerido"
        seguridad_str = " | ".join(tarea.safety_precautions)

        texto_plan += (
            f"TAREA {i}: {tarea.title}\n"
            f"  * Descripción: {tarea.description}\n"
            f"  * Categoría: {tarea.category.upper()} | Tiempo estimado: {tarea.estimated_duration_minutes} min\n"
            f"  * Roles necesarios: {', '.join(tarea.assigned_roles)}\n"
            f"  * Repuestos clave: {repuestos_str}\n"
            f"  * Seguridad (HSE): {seguridad_str}\n\n"
        )

    # GUARDADO EN LA TABLA DE RECOMENDACIONES (ESTADO: PENDIENTE)
    payload_db = {
        "equipment_id": equipment_id,
        "trigger_source": trigger_source,
        "trigger_reference_id": None, 
        "recommendation_text": texto_plan,
        "confidence_score": 0.95, 
        "prediction_type": "Plan Preventivo/Predictivo (IA)", 
        "status": "Pendiente"
    }
    
    recomendacion_creada = await crud_recommendation.create(db, payload_db)

    plan_final = {
        "equipment_id": str(equipment_id),
        "status": "draft",
        "is_active": True,
        **plan_dict
    }

    return {
        "plan_generado": plan_final,
        "recomendacion_generada": recomendacion_creada is not None,
        "detalle_recomendacion": recomendacion_creada,
        "error": None
    }