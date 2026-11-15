"""
Servicio Predictivo con Inteligencia Artificial (Heimdall RCM)
Arquitectura Híbrida de Dos Capas:
1. Capa ML (XGBoost/LightGBM): Análisis estadístico ultrarrápido de series de tiempo, fallas y mantenimiento.
2. Capa Cognitiva (Gemini): Traducción técnica, diagnóstico de causa raíz y planes prescriptivos.
"""

import os
import uuid
import pandas as pd
import joblib
from typing import Literal, List, Optional
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field, ValidationError

from google import genai
from google.genai import types

# Importaciones de los modelos de Heimdall RCM
from models.equipment import Equipment
from models.equipment_metrics import EquipmentMetricHistory
from models.failure_history import FailureHistory
from models.maintenance_history import MaintenanceHistory
from models.equipment_criticality import EquipmentCriticality
from models.ai_recommendation import AIRecommendation
from models.ai_correction import AICorrection
from crud import ai_recommendation as crud_recommendation
from services.notification import notify_ai_analysis_ready
from dotenv import load_dotenv

load_dotenv()

# =====================================================================
# CONFIGURACIÓN GLOBAL DE INTELIGENCIA ARTIFICIAL
# =====================================================================

# 1. Inicialización del cliente de Google GenAI con el nuevo SDK
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# 2. Carga Global del Modelo Machine Learning (XGBoost)
# Se carga una sola vez al arrancar FastAPI para que las inferencias tomen milisegundos.
try:
    MODELO_ML = joblib.load("modelo_bomba_inyeccion.pkl")
    COLUMNAS_ESPERADAS = joblib.load("columnas_modelo.pkl")
    print("[INFO] Modelo predictivo de ML Multi-Equipo cargado correctamente.")
except FileNotFoundError:
    MODELO_ML = None
    COLUMNAS_ESPERADAS = []
    print("[ADVERTENCIA] Archivos de ML no encontrados. El sistema operará sin pre-filtro estadístico.")


# =====================================================================
# FUNCIÓN AUXILIAR: IDENTIFICACIÓN DEL TIPO DE MÁQUINA
# =====================================================================
def identificar_categoria_equipo(equipment: Equipment) -> dict:
    """
    Clasifica el activo en Bomba, Compresor o Tanque revisando su tag_number,
    name, equipment_type y technical_specifications.
    """
    tag = (equipment.tag_number or "").upper()
    nombre = (equipment.name or "").upper()
    tipo = (equipment.equipment_type or "").upper()
    specs_str = str(equipment.technical_specifications or {}).upper()

    es_tanque = 0
    es_compresor = 0
    es_bomba = 0

    if "TK" in tag or "TANQUE" in nombre or "BALA" in nombre or "ESTATICO" in tipo or "ESTÁTICO" in tipo:
        es_tanque = 1
    elif "CMP" in tag or tag.startswith("K-") or "COMPRESOR" in nombre or "COMPRESSOR" in specs_str:
        es_compresor = 1
    else:
        es_bomba = 1

    return {
        "is_bomba": es_bomba,
        "is_compresor": es_compresor,
        "is_tanque": es_tanque
    }


def _safe_float(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


# =====================================================================
# FUNCIÓN AUXILIAR: EVALUACIÓN RÁPIDA CON MACHINE LEARNING (CAPA 1)
# =====================================================================
def evaluar_metrica_actual_ml(
    equipment: Equipment,
    metricas_orm: list,
    ultimas_fallas: list | None = None,
    ultimos_mantenimientos: list | None = None
) -> dict:
    """
    Toma el activo, su historial de lecturas recientes, su historial de fallas y
    mantenimientos, aplana todas las variables en un DataFrame de Pandas, calcula
    las derivadas temporales (medias móviles, deltas) y ejecuta la predicción sobre
    la métrica más reciente para Bombas, Compresores y Tanques.
    """
    if not MODELO_ML or not metricas_orm:
        return {
            "probabilidad_falla": 0.0,
            "clasificacion_alerta": "SIN DATOS ML",
            "salto_amperaje": 0.0,
            "dias_ultima_falla": 0.0,
            "dias_ultimo_mantenimiento": 0.0
        }

    ultimas_fallas = ultimas_fallas or []
    ultimos_mantenimientos = ultimos_mantenimientos or []

    cat_flags = identificar_categoria_equipo(equipment)
    tech_specs = equipment.technical_specifications or {}

    # Cálculo de variables históricas de Fallas y Mantenimiento
    ahora = datetime.now(timezone.utc)
    prev_failures_count = len(ultimas_fallas)
    historical_downtime_hours = sum(_safe_float(getattr(f, "downtime_hours", 0.0)) for f in ultimas_fallas)

    if ultimas_fallas and getattr(ultimas_fallas[0], "failure_date", None):
        f_date = ultimas_fallas[0].failure_date
        if f_date.tzinfo is None:
            f_date = f_date.replace(tzinfo=timezone.utc)
        days_since_last_failure = max((ahora - f_date).total_seconds() / 86400.0, 0.0)
    else:
        days_since_last_failure = 180.0  # Valor base si no registra fallas recientes

    if ultimos_mantenimientos and getattr(ultimos_mantenimientos[0], "execution_date", None):
        m_date = ultimos_mantenimientos[0].execution_date
        if m_date.tzinfo is None:
            m_date = m_date.replace(tzinfo=timezone.utc)
        days_since_last_maint = max((ahora - m_date).total_seconds() / 86400.0, 0.0)
    else:
        days_since_last_maint = 60.0  # Valor base si no registra mantenimientos recientes

    data = []
    for m in metricas_orm:
        specs = m.specific_metrics or {}

        # Extracción compatible con Bombas, Compresores y Tanques
        presion_descarga = _safe_float(
            specs.get("presion_descarga_psi", specs.get("presion_psi", specs.get("Presión de descarga (psig)", tech_specs.get("presion_descarga_psi", 0.0))))
        )
        presion_succion = _safe_float(
            specs.get("presion_succion_psi", tech_specs.get("presion_succion_psi", 0.0))
        )
        caudal_gas = _safe_float(
            specs.get("caudal_mmscfd", tech_specs.get("caudal_mmscfd", 0.0))
        )
        velocidad_rpm = _safe_float(
            specs.get("velocidad_rpm", specs.get("rpm", specs.get("Velocidad (RPM)", tech_specs.get("velocidad_rpm", tech_specs.get("rpm", 0.0)))))
        )

        data.append({
            "recorded_at": m.recorded_at,
            "is_bomba": cat_flags["is_bomba"],
            "is_compresor": cat_flags["is_compresor"],
            "is_tanque": cat_flags["is_tanque"],
            "temperature_celsius": _safe_float(m.temperature_celsius),
            "vibration_mm_s": _safe_float(m.vibration_mm_s),
            "operating_hours": _safe_float(m.operating_hours, _safe_float(equipment.usage_time)),
            "flpPsi": _safe_float(specs.get("flpPsi", tech_specs.get("flpPsi", 0.0))),
            "thpPsi": _safe_float(specs.get("thpPsi", tech_specs.get("thpPsi", 0.0))),
            "motorAmps": _safe_float(specs.get("motorAmps", tech_specs.get("motorAmps", 0.0))),
            "flowRateBpd": _safe_float(specs.get("flowRateBpd", tech_specs.get("flowRateBpd", 0.0))),
            "waterCutPercent": _safe_float(specs.get("waterCutPercent", tech_specs.get("waterCutPercent", 0.0))),
            "presion_succion_psi": presion_succion,
            "presion_descarga_psi": presion_descarga,
            "caudal_mmscfd": caudal_gas,
            "velocidad_rpm": velocidad_rpm,
            "internal_pressure_psi": _safe_float(specs.get("internal_pressure_psi", 0.0)),
            "vapor_pressure_psi": _safe_float(specs.get("vapor_pressure_psi", 0.0)),
            "liquid_level_percentage": _safe_float(specs.get("liquid_level_percentage", 0.0)),
            "prev_failures_count": prev_failures_count,
            "days_since_last_failure": round(days_since_last_failure, 2),
            "days_since_last_maint": round(days_since_last_maint, 2),
            "historical_downtime_hours": round(historical_downtime_hours, 2)
        })

    # Ordenar cronológicamente (ascendente) para que los cálculos de media móvil tengan sentido físico
    df = pd.DataFrame(data).sort_values("recorded_at").reset_index(drop=True)

    # Calcular las características rodantes (Rolling Features) para los 3 tipos de equipos
    ventanas = [
        "temperature_celsius", "vibration_mm_s", "motorAmps",
        "flowRateBpd", "presion_descarga_psi", "internal_pressure_psi"
    ]
    for col in ventanas:
        if col in df.columns:
            df[f"{col}_media_12h"] = df[col].rolling(window=12, min_periods=1).mean()
            df[f"{col}_std_12h"] = df[col].rolling(window=12, min_periods=1).std().fillna(0)
            df[f"{col}_delta"] = df[col].diff().fillna(0)

    # Alinear las columnas exactamente como las espera el modelo XGBoost
    for col in COLUMNAS_ESPERADAS:
        if col not in df.columns:
            df[col] = 0.0

    # Extraer únicamente el último registro (el estado actual de la máquina)
    ultima_lectura = df[COLUMNAS_ESPERADAS].iloc[[-1]]

    # Inferencia (probabilidad de que la clase sea 1 = Falla Inminente en < 48h)
    prob_falla = float(MODELO_ML.predict_proba(ultima_lectura)[0, 1])

    return {
        "probabilidad_falla": round(prob_falla, 4),
        "clasificacion_alerta": "CRÍTICA" if prob_falla >= 0.70 else ("MODERADA" if prob_falla >= 0.40 else "NORMAL"),
        "salto_amperaje": round(float(df["motorAmps_delta"].iloc[-1]), 2) if "motorAmps_delta" in df.columns else 0.0,
        "dias_ultima_falla": round(days_since_last_failure, 1),
        "dias_ultimo_mantenimiento": round(days_since_last_maint, 1)
    }


# =====================================================================
# CONTRATOS DE DATOS (ESQUEMAS PYDANTIC) PARA ESTRUCTURAR RESPUESTAS GEMINI
# =====================================================================
class InformeConfiabilidadRCM(BaseModel):
    requiere_intervencion: bool = Field(description="True si se detecta anomalía. False si opera normal.")
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
    hipotesis_causa_raiz: str = Field(description="Explicación técnica de la alerta del modelo ML")
    normas_aplicadas: List[str] = Field(description="Lista de normas de confiabilidad (ej. ISO 14224)")
    plan_accion: List[str] = Field(description="Pasos correctivos concretos a seguir en campo")

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
# ENDPOINT INTERNO 1: ANÁLISIS PREDICTIVO DETALLADO POR EQUIPO (CAPA 2)
# =====================================================================
async def ejecutar_analisis_predictivo_ia(
    db: AsyncSession, 
    equipment_id: uuid.UUID, 
    trigger_source: str, 
    trigger_reference_id: uuid.UUID | None = None
) -> dict:
    """
    Evalúa profundamente a un equipo específico (Bomba, Compresor o Tanque).
    Llamado manual por el usuario o automáticamente si una métrica sale de rango.
    """
    equipment = (await db.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one_or_none()
    if not equipment:
        return {"analisis_ia": None, "error": "Equipo no encontrado", "recomendacion_generada": False}

    criticality = (await db.execute(select(EquipmentCriticality).where(EquipmentCriticality.equipment_id == equipment_id))).scalar_one_or_none()
    
    # 1. Extracción de datos del historial
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

    # 2. Búsqueda de Feedback Loop (Correcciones Humanas)
    correcciones_query = (await db.execute(
        select(AICorrection, AIRecommendation)
        .join(AIRecommendation, AICorrection.recommendation_id == AIRecommendation.id)
        .where(AIRecommendation.equipment_id == equipment_id)
        .order_by(AICorrection.created_at.desc())
        .limit(3)
    )).all()

    str_correcciones = "NO HAY CORRECCIONES HUMANAS PREVIAS."
    if correcciones_query:
        str_correcciones = "HISTORIAL DE CORRECCIONES (APRENDIZAJE DEL AUDITOR TÉCNICO):\n"
        for corr, rec in correcciones_query:
            str_correcciones += f"- La IA alertó: '{rec.prediction_type}'. El humano corrigió y estableció: '{corr.corrected_text}'\n"

    # 3. PRE-FILTRO: EJECUCIÓN DEL MACHINE LEARNING SOBRE EL ESTADO ACTUAL + HISTORIAL DE FALLAS Y MANTENIMIENTO
    resultado_ml = evaluar_metrica_actual_ml(
        equipment=equipment,
        metricas_orm=metricas_recientes,
        ultimas_fallas=ultimas_fallas,
        ultimos_mantenimientos=ultimos_mantenimientos
    )
    
    str_machine_learning = "SIN DATOS SUFICIENTES PARA EVALUACIÓN ML."
    if metricas_recientes and MODELO_ML:
        str_machine_learning = (
            f"RESULTADOS DEL MODELO ESTADÍSTICO DE MACHINE LEARNING (MULTI-EQUIPO):\n"
            f"Probabilidad de Falla Inminente (<48h): {resultado_ml['probabilidad_falla'] * 100}%\n"
            f"Clasificación de Alerta: {resultado_ml['clasificacion_alerta']}\n"
            f"Salto abrupto de amperaje (Delta): {resultado_ml['salto_amperaje']} A respecto al historial reciente.\n"
            f"Días desde última falla: {resultado_ml['dias_ultima_falla']} días | Días desde último mantenimiento: {resultado_ml['dias_ultimo_mantenimiento']} días.\n"
        )

    # 4. Formateo de las métricas crudas para dárselas de contexto a Gemini
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

    str_fallas = "\n".join([f"{f.failure_date} | Modo: {f.failure_mode} | Severidad: {f.severity} | Horas Parada: {f.downtime_hours} | Desc: {f.description}" for f in ultimas_fallas]) or "NINGUNA REGISTRADA."
    str_mantenimientos = "\n".join([f"{m.execution_date} | Acción ejecutada: {m.action_taken} | Repuestos: {m.replaced_parts}" for m in ultimos_mantenimientos]) or "NINGUNO REGISTRADO."

    specs = equipment.technical_specifications or {}
    umbrales = specs.get("standard_metric", "No definidos")
    
    str_criticidad = "NO EVALUADA"
    if criticality:
        str_criticidad = (
            f"Nivel {criticality.criticality_level} (RPN: {criticality.rpn_score})\n"
            f"Impactos -> Seguridad: {criticality.safety_impact_score} | Ambiental: {criticality.environmental_impact_score} | "
            f"Operacional: {criticality.operational_impact_score} | Costo: {criticality.maintenance_cost_score}"
        )

    # 5. CONSTRUCCIÓN DEL CONTEXTO MAESTRO PARA GEMINI
    contexto_tecnico = (
        f"PERFIL DEL ACTIVO:\n"
        f"Tag: {equipment.tag_number} | Nombre: {equipment.name} | Tipo: {equipment.equipment_type}\n"
        f"Marca/Modelo: {equipment.brand or 'N/D'} - {equipment.model or 'N/D'}\n"
        f"Estado Operativo: {equipment.operational_status.upper()} | Horas de Uso Acumuladas: {equipment.usage_time} hrs\n"
        f"Umbrales Normales Operativos: {umbrales}\n\n"
        f"ANÁLISIS DE CRITICIDAD:\n{str_criticidad}\n\n"
        f"{str_machine_learning}\n\n"
        f"{str_correcciones}\n\n"
        f"ANÁLISIS DE TELEMETRÍA (ACTUAL VS HISTÓRICO):\n{str_metricas}\n\n"
        f"HISTORIAL DE FALLAS REALES:\n{str_fallas}\n\n"
        f"HISTORIAL DE MANTENIMIENTOS EJECUTADOS:\n{str_mantenimientos}"
    )

    # 6. REGLAS DE NEGOCIO PARA EL MODELO GENERATIVO
    instrucciones_rcm = (
        "Eres un Ingeniero Jefe de Confiabilidad CMRP experto en Análisis de Tendencias CBM para Bombas, Compresores y Tanques.\n\n"
        "REGLAS ESTRICTAS ANTI-ALUCINACIONES:\n"
        "1. EXPLICACIÓN ML: Recibes un diagnóstico probabilístico (%). Tu trabajo es EXPLICAR físicamente por qué el algoritmo asignó ese porcentaje basándote en el salto temporal de la telemetría, fallas previas y mantenimientos.\n"
        "2. CERO INVENTOS: Si el ML arroja baja probabilidad (<40%) y los valores están dentro de umbrales, decreta 'Operación Normal'. NO inventes fallas.\n"
        "3. HISTORIAL DE CORRECCIONES: Lee atentamente las correcciones de los expertos. Si la telemetría muestra un pico similar a una alerta pasada que el experto desestimó, IGNORA la anomalía estadística y decreta operación normal.\n"
        "4. CRITICIDAD E IMPACTO: Si detectas anomalía real, revisa los puntajes de Seguridad o Ambiental para incluir contenciones preventivas urgentes en tu plan de acción.\n"
        "5. CORRELACIÓN HISTÓRICA: Usa el 'Historial de Fallas' y 'Historial de Mantenimientos' para justificar tus hipótesis (Ej: 'Este aumento precede a la rotura vista en X fecha')."
    )

    configuracion = types.GenerateContentConfig(
        system_instruction=instrucciones_rcm,
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=InformeConfiabilidadRCM,
    )

    try:
        respuesta = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=contexto_tecnico,
            config=configuracion
        )
        resultado_obj = InformeConfiabilidadRCM.model_validate_json(respuesta.text)
        
        resultado_dict = resultado_obj.model_dump()
        resultado_dict["probabilidad_ml"] = resultado_ml['probabilidad_falla']
        
    except Exception as e:
        print(f"[ERROR IA] Fallo en análisis predictivo (Gemini): {e}")
        return {"analisis_ia": None, "error": str(e), "recomendacion_generada": False}

    # 7. GENERACIÓN DEL REPORTE TEXTUAL Y GUARDADO EN LA BASE DE DATOS
    recomendacion_creada = None
    
    if resultado_obj.requiere_intervencion:
        normas_str = " , ".join(resultado_obj.normas_aplicadas)
        plan_accion_str = "\n".join([f"{i}. {accion}" for i, accion in enumerate(resultado_obj.plan_accion, start=1)])

        informe_texto = (
            f"DIAGNÓSTICO Y PRESCRIPCIÓN\n"
            f"INFORME DE CONFIABILIDAD Y DIAGNÓSTICO TÉCNICO (CMRP / ISO 55000)\n"
            f"ALERTA DEL MODELO ESTADÍSTICO: {resultado_ml['probabilidad_falla']*100}% DE PROBABILIDAD DE FALLA.\n"
            f"DIAGNÓSTICO FINAL: {resultado_obj.diagnostico_principal.upper()}\n"
            f"NIVEL DE CONFIANZA IA: {int(resultado_obj.confianza * 100)}%\n\n"
            f"1. EVALUACIÓN DE CONDICIÓN Y CORRELACIÓN HISTÓRICA:\n"
            f"{resultado_obj.evaluacion_condicion}\n\n"
            f"2. HIPÓTESIS DE CAUSA RAÍZ (EXPLICACIÓN FÍSICA DE LA ALERTA):\n"
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
        
        if recomendacion_creada:
            await notify_ai_analysis_ready(
                db=db,
                title="🧠 Análisis Predictivo IA Listo",
                message=f"La IA ha generado un dictamen técnico de riesgo para el equipo {equipment.tag_number}.",
                user_id=None
            )

    return {
        "analisis_ia": resultado_dict, 
        "recomendacion_generada": recomendacion_creada is not None,
        "detalle_recomendacion": recomendacion_creada
    }


# =====================================================================
# ENDPOINT INTERNO 2: GENERACIÓN DE PLAN DE MANTENIMIENTO ESTRUCTURADO
# =====================================================================
async def generar_plan_mantenimiento_ia(
    db: AsyncSession, 
    equipment_id: uuid.UUID,
    contexto_diagnostico: str,
    trigger_source: str = "Asistente IA - Generación de Plan"
) -> dict:
    """
    Toma el diagnóstico de riesgo previo (de Gemini o manual) y estructura 
    un plan de mantenimiento riguroso con repuestos, roles y seguridad.
    """
    equipment = (await db.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one_or_none()
    if not equipment:
        return {"plan_generado": None, "error": "Equipo no encontrado", "recomendacion_generada": False}

    instrucciones_planificador = (
        "Eres un Planificador Senior de Mantenimiento Industrial riguroso.\n\n"
        "REGLAS ESTRICTAS:\n"
        "1. CERO INVENTOS: Solo planifica tareas y repuestos estrictamente necesarios para resolver el 'Contexto o Diagnóstico' proporcionado. No agregues tareas genéricas si no aplican.\n"
        "2. Especifica repuestos realistas (códigos técnicos estándar) y herramientas exactas (ej. Torquímetro 1/2 pulg 50-250 ft-lb).\n"
        "3. Incluye precauciones de seguridad rigurosas según la industria (Análisis de Trabajo Seguro, LOTO, Trabajos en Caliente, Espacios Confinados).\n"
        "4. Calcula horas estimadas de forma pragmática según la suma de las tareas.\n"
        "5. Fechas obligatoriamente en formato ISO 8601 (Z)."
    )

    datos_entrada = (
        f"DATOS DEL EQUIPO:\n"
        f"Tag: {equipment.tag_number}\n"
        f"Nombre: {equipment.name}\n"
        f"Tipo: {equipment.equipment_type}\n"
        f"Marca/Modelo: {equipment.brand or 'N/D'} - {equipment.model or 'N/D'}\n"
        f"Estado Operativo Actual: {equipment.operational_status.upper()}\n\n"
        f"CONTEXTO O DIAGNÓSTICO PREDICTIVO PARA GENERAR EL PLAN:\n"
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
        print(f"[ERROR PYDANTIC] Fallo en el contrato del plan de mantenimiento: {e}")
        return {"plan_generado": None, "error": "Fallo en validación estructural del JSON devuelto por IA.", "recomendacion_generada": False}
    except Exception as e:
        print(f"[ERROR IA] Fallo generando plan estructurado: {e}")
        return {"plan_generado": None, "error": str(e), "recomendacion_generada": False}

    texto_plan = (
        f"PROPUESTA DE PLAN DE MANTENIMIENTO: {plan_obj.title.upper()}\n"
        f"TIPO DE PLAN: {plan_obj.maintenance_type.upper()} | PRIORIDAD: {plan_obj.priority.upper()}\n"
        f"FRECUENCIA RECOMENDADA: {plan_obj.frequency_days} DÍAS | DURACIÓN ESTIMADA: {plan_obj.estimated_hours} HRS\n\n"
        f"JUSTIFICACIÓN TÉCNICA Y CONTEXTO DEL DIAGNÓSTICO:\n"
        f"{plan_obj.description}\n\n"
        f"DESGLOSE DE TAREAS PRINCIPALES A EJECUTAR:\n\n"
    )

    for i, tarea in enumerate(plan_obj.tasks, start=1):
        repuestos_str = " , ".join([p.name for p in tarea.required_parts]) if tarea.required_parts else "NINGUNO REQUERIDO"
        seguridad_str = " , ".join(tarea.safety_precautions)

        texto_plan += (
            f"TAREA {i}: {tarea.title.upper()}\n"
            f"DESCRIPCIÓN: {tarea.description}\n"
            f"CATEGORÍA: {tarea.category.upper()} | TIEMPO ESTIMADO: {tarea.estimated_duration_minutes} MIN\n"
            f"ROLES NECESARIOS (ESPECIALIDADES): {', '.join(tarea.assigned_roles).upper()}\n"
            f"REPUESTOS CLAVE A SOLICITAR A BODEGA: {repuestos_str.upper()}\n"
            f"SEGURIDAD Y H.S.E (CRÍTICO): {seguridad_str.upper()}\n\n"
        )

    payload_db = {
        "equipment_id": equipment_id,
        "trigger_source": trigger_source,
        "trigger_reference_id": None, 
        "recommendation_text": texto_plan,
        "confidence_score": 0.95, 
        "prediction_type": "Plan Preventivo/Predictivo (IA Generativa)", 
        "status": "Pendiente"
    }
    
    recomendacion_creada = await crud_recommendation.create(db, payload_db)
    
    if recomendacion_creada:
        await notify_ai_analysis_ready(
            db=db,
            title="📋 Plan de Mantenimiento IA Estructurado",
            message=f"Se ha estructurado un plan '{plan_obj.title}' para el equipo {equipment.tag_number}.",
            user_id=None
        )

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


# =====================================================================
# ENDPOINT INTERNO 3: ESCANEO GLOBAL DE RIESGO DE LA PLANTA (SOLO ML)
# =====================================================================
async def evaluar_riesgo_global_planta(db: AsyncSession) -> dict:
    """
    Función de altísimo rendimiento.
    Recorre TODOS los activos de la planta (Bombas, Compresores y Tanques),
    extrae sus métricas, historial de fallas y mantenimientos y los pasa por XGBoost.
    """
    equipos_activos = (await db.execute(
        select(Equipment).where(Equipment.is_active == True, Equipment.deleted_at.is_(None))
    )).scalars().all()

    equipos_en_riesgo = []
    equipos_sanos = 0

    for equipo in equipos_activos:
        metricas_recientes = (await db.execute(
            select(EquipmentMetricHistory)
            .where(EquipmentMetricHistory.equipment_id == equipo.id)
            .order_by(EquipmentMetricHistory.recorded_at.desc())
            .limit(50)
        )).scalars().all()

        if not metricas_recientes:
            continue

        ultimas_fallas = (await db.execute(
            select(FailureHistory)
            .where(FailureHistory.equipment_id == equipo.id)
            .order_by(FailureHistory.failure_date.desc())
            .limit(5)
        )).scalars().all()

        ultimos_mantenimientos = (await db.execute(
            select(MaintenanceHistory)
            .where(MaintenanceHistory.equipment_id == equipo.id)
            .order_by(MaintenanceHistory.execution_date.desc())
            .limit(5)
        )).scalars().all()

        # Evaluamos el vector de datos completo usando el modelo matemático local
        resultado_ml = evaluar_metrica_actual_ml(
            equipment=equipo,
            metricas_orm=metricas_recientes,
            ultimas_fallas=ultimas_fallas,
            ultimos_mantenimientos=ultimos_mantenimientos
        )
        
        if resultado_ml["probabilidad_falla"] >= 0.40:
            equipos_en_riesgo.append({
                "equipment_id": str(equipo.id),
                "tag_number": equipo.tag_number,
                "name": equipo.name,
                "probabilidad_falla": resultado_ml["probabilidad_falla"],
                "alerta": resultado_ml["clasificacion_alerta"],
                "ultima_actualizacion": metricas_recientes[0].recorded_at.isoformat()
            })
        else:
            equipos_sanos += 1

    equipos_en_riesgo = sorted(equipos_en_riesgo, key=lambda x: x["probabilidad_falla"], reverse=True)

    return {
        "total_analizados": len(equipos_activos),
        "equipos_sanos": equipos_sanos,
        "equipos_en_riesgo_count": len(equipos_en_riesgo),
        "alertas": equipos_en_riesgo
    }


# =====================================================================
# ENDPOINT INTERNO 4: GENERACIÓN EN LOTE DE PAUTAS DE MANTENIMIENTO
# =====================================================================
async def generar_planes_mantenimiento_globales(db: AsyncSession, trigger_source: str) -> dict:
    """
    Función de Orquestación (Batch).
    1. Llama al Radar Predictivo (ML) para ubicar a las máquinas enfermas.
    2. Delega a Gemini (IA Generativa) la creación de un plan de medicina preventiva
       específico para cada máquina en rojo.
    """
    analisis_global = await evaluar_riesgo_global_planta(db)
    equipos_criticos = analisis_global["alertas"]
    
    planes_generados = []
    errores = []

    for equipo_alerta in equipos_criticos:
        contexto_diagnostico = (
            f"El modelo predictivo de Machine Learning ha detectado una probabilidad de falla estadística del "
            f"{equipo_alerta['probabilidad_falla'] * 100}%. Nivel de alerta: {equipo_alerta['alerta']}. "
            f"Se requiere formular un plan de inspección, cambio de consumibles y contención inmediata basado en esta condición de alarma."
        )
        
        resultado_plan = await generar_plan_mantenimiento_ia(
            db=db,
            equipment_id=uuid.UUID(equipo_alerta["equipment_id"]),
            contexto_diagnostico=contexto_diagnostico,
            trigger_source=trigger_source
        )
        
        if resultado_plan.get("error"):
            errores.append({"equipment_id": equipo_alerta["equipment_id"], "error": resultado_plan["error"]})
        else:
            planes_generados.append(resultado_plan["plan_generado"])

    return {
        "planes_creados": len(planes_generados),
        "errores": errores,
        "detalle_planes": planes_generados
    }