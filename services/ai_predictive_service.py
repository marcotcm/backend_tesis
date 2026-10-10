import os
import uuid
from typing import Literal, List, Optional
from datetime import datetime, timezone

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
    evaluacion_condicion: str = Field(description="Análisis de tendencia comparando métrica actual vs histórico")
    hipotesis_causa_raiz: str = Field(description="Explicación técnica estricta basada solo en los datos provistos")
    normas_aplicadas: List[str] = Field(description="Lista de normas (ej. ISO 20816-3, SAE JA1011)")
    plan_accion: List[str] = Field(description="Pasos correctivos concretos a seguir")

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
    required_tools: List[str] = Field(description="Herramientas necesarias (ej. Torquímetro)")
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
# FUNCIÓN 1: ANÁLISIS PREDICTIVO (TENDENCIAS Y RIGOR MATEMÁTICO)
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
    
    # Histórico de métricas limitado a las últimas 50 lecturas (sin límite de fecha)
    metricas_recientes = (await db.execute(
        select(EquipmentMetricHistory)
        .where(EquipmentMetricHistory.equipment_id == equipment_id)
        .order_by(EquipmentMetricHistory.recorded_at.desc())
        .limit(50)
    )).scalars().all()

    ultimas_fallas = (await db.execute(
        select(FailureHistory).where(FailureHistory.equipment_id == equipment_id).order_by(FailureHistory.failure_date.desc()).limit(5)
    )).scalars().all()

    ultimos_mantenimientos = (await db.execute(
        select(MaintenanceHistory).where(MaintenanceHistory.equipment_id == equipment_id).order_by(MaintenanceHistory.execution_date.desc()).limit(5)
    )).scalars().all()

    # Formateo de métricas con separación para análisis de tendencia y soporte para specific_metrics
    str_metricas = "NO HAY DATOS DE CONDICIÓN REGISTRADOS."
    if metricas_recientes:
        metrica_actual = metricas_recientes[0]
        historico = metricas_recientes[1:]
        
        extras_actual = f" | Otras: {metrica_actual.specific_metrics}" if metrica_actual.specific_metrics else ""
        str_metricas = (
            f"ÚLTIMA LECTURA REGISTRADA (ESTADO ACTUAL):\n"
            f"{metrica_actual.recorded_at} | Temp: {metrica_actual.temperature_celsius}°C | Vib: {metrica_actual.vibration_mm_s} mm/s | Horas Op: {metrica_actual.operating_hours}{extras_actual} | Notas: {metrica_actual.notes}\n\n"
        )
        
        if historico:
            str_metricas += f"HISTÓRICO PREVIO (PARA CALCULAR TENDENCIA):\n"
            for m in historico:
                extras_hist = f" | Otras: {m.specific_metrics}" if m.specific_metrics else ""
                str_metricas += f"{m.recorded_at} | Temp: {m.temperature_celsius}°C | Vib: {m.vibration_mm_s} mm/s | Horas Op: {m.operating_hours}{extras_hist} | Notas: {m.notes}\n"
        else:
            str_metricas += "HISTÓRICO PREVIO: NO HAY DATOS SUFICIENTES PARA ESTABLECER TENDENCIA."

    # Formateo del resto de datos históricos
    str_fallas = "\n".join([f"{f.failure_date} | Modo: {f.failure_mode} | Severidad: {f.severity} | Horas Parada: {f.downtime_hours} | Desc: {f.description}" for f in ultimas_fallas]) or "NINGUNA REGISTRADA."
    str_mantenimientos = "\n".join([f"{m.execution_date} | Acción ejecutada: {m.action_taken} | Repuestos: {m.replaced_parts}" for m in ultimos_mantenimientos]) or "NINGUNO REGISTRADO."

    # Datos técnicos base y criticidad profunda
    specs = equipment.technical_specifications or {}
    umbrales = specs.get("standard_metric", "No definidos")
    
    str_criticidad = "NO EVALUADA"
    if criticality:
        str_criticidad = (
            f"Nivel {criticality.criticality_level} (RPN: {criticality.rpn_score})\n"
            f"Impactos -> Seguridad: {criticality.safety_impact_score} | Ambiental: {criticality.environmental_impact_score} | "
            f"Operacional: {criticality.operational_impact_score} | Costo: {criticality.maintenance_cost_score}"
        )

    contexto_tecnico = (
        f"PERFIL DEL ACTIVO:\n"
        f"Tag: {equipment.tag_number} | Nombre: {equipment.name} | Tipo: {equipment.equipment_type}\n"
        f"Marca/Modelo: {equipment.brand or 'N/D'} - {equipment.model or 'N/D'}\n"
        f"Función Principal: {equipment.function_description or 'N/D'}\n"
        f"Estado Operativo: {equipment.operational_status.upper()} | Horas de Uso Acumuladas: {equipment.usage_time} hrs\n"
        f"Umbrales Normales Operativos: {umbrales}\n\n"
        f"ANÁLISIS DE CRITICIDAD:\n{str_criticidad}\n\n"
        f"ANÁLISIS DE TELEMETRÍA (ACTUAL VS HISTÓRICO):\n{str_metricas}\n\n"
        f"HISTORIAL DE FALLAS REALES:\n{str_fallas}\n\n"
        f"HISTORIAL DE MANTENIMIENTOS EJECUTADOS:\n{str_mantenimientos}"
    )

    instrucciones_rcm = (
        "Eres un Ingeniero Jefe de Confiabilidad CMRP experto en Análisis de Tendencias CBM.\n\n"
        "REGLAS ESTRICTAS ANTI-ALUCINACIONES:\n"
        "1. COMPARA EXPLICITAMENTE: Evalúa la 'ÚLTIMA LECTURA' contra el 'HISTÓRICO PREVIO', las 'Horas de Operación' y los 'Umbrales'. ¿Hay un salto brusco? ¿Degradación lenta? ¿O es ruido?\n"
        "2. CERO INVENTOS: Si los valores están estables y dentro de umbrales, el diagnóstico DEBE ser 'Operación Normal'. NO inventes fallas.\n"
        "3. CRITICIDAD E IMPACTO: Si detectas una anomalía real, revisa los puntajes de Seguridad o Ambiental. Si son altos, recomienda medidas de contención preventivas en tu plan de acción.\n"
        "4. CORRELACIÓN HISTÓRICA: Usa el 'Historial de Fallas Reales' y los 'Mantenimientos Ejecutados' para justificar tu Hipótesis de Causa Raíz."
    )

    configuracion = types.GenerateContentConfig(
        system_instruction=instrucciones_rcm,
        temperature=0.0, 
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
        normas_str = " , ".join(resultado_obj.normas_aplicadas)
        plan_accion_str = "\n".join([f"{i}. {accion}" for i, accion in enumerate(resultado_obj.plan_accion, start=1)])

        # TEXTO PLANO LIMPIO (SIN GUIONES, ASTERISCOS NI SEPARADORES)
        informe_texto = (
            f"DIAGNÓSTICO Y PRESCRIPCIÓN\n"
            f"INFORME DE CONFIABILIDAD Y DIAGNÓSTICO TÉCNICO (CMRP / ISO 55000)\n"
            f"DIAGNÓSTICO: {resultado_obj.diagnostico_principal.upper()}\n"
            f"NIVEL DE CONFIANZA: {int(resultado_obj.confianza * 100)}%\n\n"
            f"1. EVALUACIÓN DE CONDICIÓN Y CORRELACIÓN HISTÓRICA:\n"
            f"{resultado_obj.evaluacion_condicion}\n\n"
            f"2. HIPÓTESIS DE CAUSA RAÍZ:\n"
            f"{resultado_obj.hipotesis_causa_raiz}\n\n"
            f"3. NORMAS Y PRINCIPIOS APLICADOS:\n"
            f"{normas_str}\n\n"
            f"4. PLAN DE ACCIÓN INMEDIATO PARA PLANIFICACIÓN:\n"
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
# FUNCIÓN 2: GENERACIÓN DE PLAN DE MANTENIMIENTO IA (RIGUROSO)
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
        "Eres un Planificador Senior de Mantenimiento Industrial riguroso.\n\n"
        "REGLAS ESTRICTAS:\n"
        "1. CERO INVENTOS: Solo planifica tareas y repuestos estrictamente necesarios para resolver el 'Contexto o Diagnóstico' proporcionado. No agregues tareas genéricas si no aplican.\n"
        "2. Especifica repuestos realistas (códigos técnicos) y herramientas exactas (ej. Torquímetro 1/2 pulg 50-250 ft-lb).\n"
        "3. Incluye precauciones de seguridad rigurosas según la industria.\n"
        "4. Calcula horas estimadas de forma matemática según la suma de las tareas.\n"
        "5. Fechas en formato ISO 8601 (Z)."
    )

    datos_entrada = (
        f"DATOS DEL EQUIPO:\n"
        f"Tag: {equipment.tag_number}\n"
        f"Nombre: {equipment.name}\n"
        f"Tipo: {equipment.equipment_type}\n"
        f"Marca/Modelo: {equipment.brand or 'N/D'} - {equipment.model or 'N/D'}\n"
        f"Estado Operativo Actual: {equipment.operational_status.upper()}\n\n"
        f"CONTEXTO O DIAGNÓSTICO PARA GENERAR EL PLAN:\n"
        f"{contexto_diagnostico}"
    )

    configuracion = types.GenerateContentConfig(
        system_instruction=instrucciones_planificador,
        temperature=0.0, 
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

    # TEXTO PLANO LIMPIO (SIN GUIONES, ASTERISCOS NI SEPARADORES)
    texto_plan = (
        f"PROPUESTA DE PLAN DE MANTENIMIENTO: {plan_obj.title.upper()}\n"
        f"TIPO DE PLAN: {plan_obj.maintenance_type.upper()} | PRIORIDAD: {plan_obj.priority.upper()}\n"
        f"FRECUENCIA: {plan_obj.frequency_days} DÍAS | DURACIÓN ESTIMADA: {plan_obj.estimated_hours} HRS\n\n"
        f"JUSTIFICACIÓN TÉCNICA Y CONTEXTO:\n"
        f"{plan_obj.description}\n\n"
        f"DESGLOSE DE TAREAS PRINCIPALES:\n\n"
    )

    for i, tarea in enumerate(plan_obj.tasks, start=1):
        repuestos_str = " , ".join([p.name for p in tarea.required_parts]) if tarea.required_parts else "NINGUNO REQUERIDO"
        seguridad_str = " , ".join(tarea.safety_precautions)

        texto_plan += (
            f"TAREA {i}: {tarea.title.upper()}\n"
            f"DESCRIPCIÓN: {tarea.description}\n"
            f"CATEGORÍA: {tarea.category.upper()} | TIEMPO ESTIMADO: {tarea.estimated_duration_minutes} MIN\n"
            f"ROLES NECESARIOS: {', '.join(tarea.assigned_roles).upper()}\n"
            f"REPUESTOS CLAVE: {repuestos_str.upper()}\n"
            f"SEGURIDAD (HSE): {seguridad_str.upper()}\n\n"
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