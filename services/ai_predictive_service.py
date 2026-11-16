"""
Servicio Predictivo con Inteligencia Artificial (Heimdall RCM)
Arquitectura Híbrida de Dos Capas:
1. Capa ML (XGBoost/LightGBM): Análisis estadístico ultrarrápido de series de tiempo, fallas y mantenimiento.
2. Capa Cognitiva (Gemini + Contingencia con Datos Reales): Traducción técnica, diagnóstico de causa raíz y planes prescriptivos.
Regla de Persistencia:
- El Análisis Predictivo SOLO se guarda en `ai_recommendations` (y notifica) si existe probabilidad de falla (>=40%), anomalía en `standard_metric` o disparo por métrica anómala.
- El Plan de Mantenimiento SIEMPRE se guarda en `ai_recommendations` (y notifica).
"""

import os
import uuid
import pandas as pd
import joblib
from typing import Literal, List, Optional
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field, ValidationError

from google import genai
from google.genai import types

# Importaciones de sesión y modelos de Heimdall RCM
from db.session import AsyncSessionLocal
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
try:
    MODELO_ML = joblib.load("modelo_bomba_inyeccion.pkl")
    COLUMNAS_ESPERADAS = joblib.load("columnas_modelo.pkl")
    print("[INFO] Modelo predictivo de ML Multi-Equipo cargado correctamente.")
except FileNotFoundError:
    MODELO_ML = None
    COLUMNAS_ESPERADAS = []
    print("[ADVERTENCIA] Archivos de ML no encontrados. El sistema operará sin pre-filtro estadístico.")


# =====================================================================
# TRADUCCIONES LEGIBLES PARA EL MODAL DE AUDITORÍA
# =====================================================================
TRADUCCION_PRIORIDAD = {
    "low": "Baja",
    "medium": "Media",
    "high": "Alta",
    "critical": "Crítica",
}

TRADUCCION_CATEGORIA = {
    "inspection": "Inspección",
    "lubrication": "Lubricación",
    "replacement": "Reemplazo de Componente",
    "calibration": "Calibración",
    "cleaning": "Limpieza Técnica",
}

TRADUCCION_ROLES = {
    "senior_technician": "Técnico Senior",
    "field_technician": "Técnico de Campo",
    "safety_officer": "Oficial de Seguridad (HSE)",
    "mechanical_specialist": "Especialista Mecánico",
    "instrumentation_tech": "Instrumentista",
    "electrical_tech": "Técnico Electricista",
}


def _formatear_roles(roles: List[str]) -> str:
    if not roles:
        return "Técnico de Campo"
    return ", ".join([TRADUCCION_ROLES.get(r.strip().lower(), r.replace("_", " ").title()) for r in roles])


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


def _tiene_anomalia_fisica_directa(equipment: Equipment, metrica_actual: Optional[EquipmentMetricHistory]) -> bool:
    """
    Verifica si la última lectura supera los umbrales de `standard_metric` definidos en el equipo
    (exactamente igual que services/equipment_metrics.py) o los umbrales físicos ISO 10816-3.
    """
    if not metrica_actual:
        return False

    # 1. Revisar contra el diccionario 'standard_metric' del propio equipo en BD
    if equipment and isinstance(equipment.technical_specifications, dict):
        standard_metric = equipment.technical_specifications.get("standard_metric", {})
        if isinstance(standard_metric, dict):
            if "temperature_celsius" in standard_metric and metrica_actual.temperature_celsius is not None:
                t_limits = standard_metric["temperature_celsius"]
                if isinstance(t_limits, dict):
                    t_min = t_limits.get("min", -50)
                    t_max = t_limits.get("max", 1000)
                    if metrica_actual.temperature_celsius < t_min or metrica_actual.temperature_celsius > t_max:
                        return True

            if "vibration_mm_s" in standard_metric and metrica_actual.vibration_mm_s is not None:
                v_limits = standard_metric["vibration_mm_s"]
                if isinstance(v_limits, dict):
                    v_min = v_limits.get("min", 0)
                    v_max = v_limits.get("max", 100)
                    if metrica_actual.vibration_mm_s < v_min or metrica_actual.vibration_mm_s > v_max:
                        return True

            if isinstance(metrica_actual.specific_metrics, dict):
                for var_name, valor_actual in metrica_actual.specific_metrics.items():
                    if var_name in standard_metric and isinstance(standard_metric[var_name], dict):
                        val_num = _safe_float(valor_actual, None)
                        if val_num is not None:
                            s_min = standard_metric[var_name].get("min")
                            s_max = standard_metric[var_name].get("max")
                            if s_min is not None and val_num < _safe_float(s_min):
                                return True
                            if s_max is not None and val_num > _safe_float(s_max):
                                return True

    # 2. Respaldo por umbrales físicos estándar ISO 10816-3 / proceso
    cat = identificar_categoria_equipo(equipment)
    vib = _safe_float(metrica_actual.vibration_mm_s)
    temp = _safe_float(metrica_actual.temperature_celsius)
    specs = metrica_actual.specific_metrics or {}

    if cat["is_tanque"]:
        p_int = _safe_float(specs.get("internal_pressure_psi", 0.0))
        nivel = _safe_float(specs.get("liquid_level_percentage", 0.0))
        return temp >= 48.0 or p_int >= 170.0 or nivel >= 90.0
    elif cat["is_compresor"]:
        return vib >= 4.5 or temp >= 95.0
    else:
        return vib >= 4.5 or temp >= 80.0


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

    ahora = datetime.now(timezone.utc)
    prev_failures_count = len(ultimas_fallas)
    historical_downtime_hours = sum(_safe_float(getattr(f, "downtime_hours", 0.0)) for f in ultimas_fallas)

    if ultimas_fallas and getattr(ultimas_fallas[0], "failure_date", None):
        f_date = ultimas_fallas[0].failure_date
        if f_date.tzinfo is None:
            f_date = f_date.replace(tzinfo=timezone.utc)
        days_since_last_failure = max((ahora - f_date).total_seconds() / 86400.0, 0.0)
    else:
        days_since_last_failure = 180.0

    if ultimos_mantenimientos and getattr(ultimos_mantenimientos[0], "execution_date", None):
        m_date = ultimos_mantenimientos[0].execution_date
        if m_date.tzinfo is None:
            m_date = m_date.replace(tzinfo=timezone.utc)
        days_since_last_maint = max((ahora - m_date).total_seconds() / 86400.0, 0.0)
    else:
        days_since_last_maint = 60.0

    data = []
    for m in metricas_orm:
        specs = m.specific_metrics or {}

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

    df = pd.DataFrame(data).sort_values("recorded_at").reset_index(drop=True)

    ventanas = [
        "temperature_celsius", "vibration_mm_s", "motorAmps",
        "flowRateBpd", "presion_descarga_psi", "internal_pressure_psi"
    ]
    for col in ventanas:
        if col in df.columns:
            df[f"{col}_media_12h"] = df[col].rolling(window=12, min_periods=1).mean()
            df[f"{col}_std_12h"] = df[col].rolling(window=12, min_periods=1).std().fillna(0)
            df[f"{col}_delta"] = df[col].diff().fillna(0)

    for col in COLUMNAS_ESPERADAS:
        if col not in df.columns:
            df[col] = 0.0

    ultima_lectura = df[COLUMNAS_ESPERADAS].iloc[[-1]]
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
    requiere_intervencion: bool = Field(description="True si se detecta anomalía o probabilidad de falla >= 40%. False si opera normal.")
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
# FUNCIONES INTERNAS DE CONTINGENCIA (TOMAN LOS MISMOS DATOS REALES)
# =====================================================================
def _generar_informe_contingencia_mismos_datos(
    equipment: Equipment,
    criticality: Optional[EquipmentCriticality],
    metricas_recientes: list,
    ultimas_fallas: list,
    ultimos_mantenimientos: list,
    resultado_ml: dict,
    forzar_intervencion: bool = False
) -> InformeConfiabilidadRCM:
    """
    Si Gemini falla, genera la estructura InformeConfiabilidadRCM tomando exactamente
    los mismos datos del equipo y del modelo XGBoost.
    """
    cat = identificar_categoria_equipo(equipment)
    prob = resultado_ml.get("probabilidad_falla", 0.0)
    prob_pct = round(prob * 100, 1)
    alerta_ml = resultado_ml.get("clasificacion_alerta", "NORMAL")
    salto_amp = resultado_ml.get("salto_amperaje", 0.0)
    dias_falla = resultado_ml.get("dias_ultima_falla", 180.0)
    dias_maint = resultado_ml.get("dias_ultimo_mantenimiento", 60.0)

    m_actual = metricas_recientes[0] if metricas_recientes else None
    temp = _safe_float(m_actual.temperature_celsius if m_actual else 70.0)
    vib = _safe_float(m_actual.vibration_mm_s if m_actual else 2.2)
    horas = _safe_float(m_actual.operating_hours if m_actual else equipment.usage_time)
    specs_actual = (m_actual.specific_metrics if m_actual and m_actual.specific_metrics else {})

    crit_level = criticality.criticality_level if criticality and criticality.criticality_level else "Clase B"
    rpn = criticality.rpn_score if criticality and criticality.rpn_score else 160

    status_failed = (equipment.operational_status or "").strip().lower() in ["failed", "falla", "critical", "out_of_service"]
    anomalia_fisica = _tiene_anomalia_fisica_directa(equipment, m_actual)

    tiene_probabilidad_fallar = forzar_intervencion or (prob >= 0.40) or anomalia_fisica or status_failed

    if not tiene_probabilidad_fallar:
        return InformeConfiabilidadRCM(
            requiere_intervencion=False,
            prediction_type="Operación Normal",
            confianza=0.94,
            diagnostico_principal=f"Operación estable dentro de parámetros nominales en {equipment.tag_number}",
            evaluacion_condicion=(
                f"El activo {equipment.tag_number} ({equipment.name}) presenta lecturas normales "
                f"(Temperatura: {temp} °C, Vibración: {vib} mm/s, Probabilidad ML: {prob_pct}%). No requiere intervención."
            ),
            hipotesis_causa_raiz="Ausencia de desviaciones estadísticas significativas en el modelo XGBoost.",
            normas_aplicadas=["ISO 14224", "ISO 10816-3", "SAE JA1011"],
            plan_accion=["Mantener frecuencia habitual de monitoreo rutinario por condición."]
        )

    if prob >= 0.70 or vib > 7.1 or status_failed:
        pred_type = "Alerta Crítica de Falla Inminente"
    elif prob >= 0.40 or vib >= 4.5 or anomalia_fisica:
        pred_type = "Inspección Basada en Condición (CBM)"
    else:
        pred_type = "Sustitución Preventiva Recomendada"

    txt_falla = (
        f"última falla hace {dias_falla} días ({ultimas_fallas[0].failure_mode})"
        if ultimas_fallas else f"{dias_falla} días sin fallas registradas"
    )
    txt_maint = (
        f"último mantenimiento hace {dias_maint} días ({ultimos_mantenimientos[0].action_taken})"
        if ultimos_mantenimientos else f"{dias_maint} días desde la última intervención"
    )

    if cat["is_tanque"]:
        p_int = _safe_float(specs_actual.get("internal_pressure_psi", 0.0))
        nivel = _safe_float(specs_actual.get("liquid_level_percentage", 0.0))
        diag = f"Condición de alerta en unidad estática {equipment.tag_number} ({equipment.name}) con riesgo ML del {prob_pct}%"
        eval_cond = (
            f"Lectura actual registrada en {equipment.tag_number} ({crit_level}, RPN {rpn}): temperatura {temp} °C, "
            f"presión interna {p_int} PSI, nivel {nivel}% y {horas} hrs acumuladas. "
            f"Correlación histórica: {txt_falla}; {txt_maint}."
        )
        hipotesis = (
            f"El análisis detecta desviación fuera de estándar y un {prob_pct}% de probabilidad en XGBoost ({alerta_ml}) "
            f"asociado a fatiga de empaquetaduras en bridas, diferencial de presión interna o desajuste en válvula de alivio (PSV)."
        )
        normas = ["ISO 14224", "API 653 / API 510", "SAE JA1011", "ISO 55000"]
        plan_acc = [
            f"Ejecutar aislamiento LOTO y despresurización controlada en {equipment.tag_number}.",
            "Verificar estanqueidad en bridas principales y calibración de válvula de seguridad (PSV).",
            "Efectuar inspección ultrasónica de espesores en cuerpo y conexiones."
        ]
    elif cat["is_compresor"]:
        p_desc = _safe_float(specs_actual.get("presion_descarga_psi", specs_actual.get("presion_psi", 0.0)))
        rpm = _safe_float(specs_actual.get("velocidad_rpm", specs_actual.get("rpm", 0.0)))
        diag = f"Anomalía dinámica ({vib} mm/s RMS, {temp} °C) y riesgo predictivo del {prob_pct}% en {equipment.tag_number}"
        eval_cond = (
            f"El activo {equipment.tag_number} ({crit_level}, RPN {rpn}) presenta vibración de {vib} mm/s RMS, "
            f"temperatura de {temp} °C, presión de descarga de {p_desc} PSI y velocidad de {rpm} RPM a las {horas} hrs de operación. "
            f"Antecedentes: {txt_falla}; {txt_maint}."
        )
        hipotesis = (
            f"La desviación en telemetría (Riesgo ML: {prob_pct}%, delta de corriente: {salto_amp} A) "
            f"evidencia fatiga mecánica en válvulas de succión/descarga, desgaste de anillos o desalineación de acople."
        )
        normas = ["ISO 10816-3", "ISO 14224", "API 618", "SAE JA1011"]
        plan_acc = [
            f"Aplicar bloqueo LOTO y despresurizar etapas de compresión en {equipment.tag_number}.",
            "Realizar inspección boroscópica de válvulas/cilindros y análisis espectral FFT.",
            "Ejecutar alineación láser de precisión motor-compresor y control de lubricante."
        ]
    else:
        p_desc = _safe_float(specs_actual.get("presion_descarga_psi", specs_actual.get("thpPsi", 0.0)))
        amps = _safe_float(specs_actual.get("motorAmps", 0.0))
        diag = f"Desviación vibro-térmica ({vib} mm/s RMS, {temp} °C) en equipo de bombeo {equipment.tag_number} (Riesgo ML: {prob_pct}%)"
        eval_cond = (
            f"Telemetría actual en {equipment.tag_number} ({crit_level}, RPN {rpn}): vibración {vib} mm/s RMS, "
            f"temperatura {temp} °C, corriente {amps} A (delta {salto_amp} A) y presión {p_desc} PSI con {horas} hrs de uso. "
            f"Historial: {txt_falla}; {txt_maint}."
        )
        hipotesis = (
            f"Se registra condición fuera de umbral operativo (Riesgo ML <48h: {prob_pct}%) debido al comportamiento "
            f"de vibración ({vib} mm/s) y temperatura ({temp} °C), indicando desgaste en pistas de rodamientos o fatiga en sello mecánico."
        )
        normas = ["ISO 10816-3", "ISO 14224", "API 610", "SAE JA1011"]
        plan_acc = [
            f"Aplicar bloqueo y etiquetado LOTO en el sistema de potencia de {equipment.tag_number}.",
            "Inspeccionar estado del sello mecánico, holgura de rodamientos y calidad del lubricante.",
            "Corregir alineación láser del eje y validar reducción de vibración a Zona A/B (< 4.5 mm/s)."
        ]

    return InformeConfiabilidadRCM(
        requiere_intervencion=True,
        prediction_type=pred_type,
        confianza=0.92,
        diagnostico_principal=diag,
        evaluacion_condicion=eval_cond,
        hipotesis_causa_raiz=hipotesis,
        normas_aplicadas=normas,
        plan_accion=plan_acc
    )


def _generar_plan_contingencia_mismos_datos(
    equipment: Equipment,
    contexto_diagnostico: str,
    metricas_recientes: list,
    resultado_ml: dict
) -> PlanMantenimientoIA:
    """
    Si Gemini falla al estructurar el plan, genera el mismo objeto PlanMantenimientoIA
    usando los datos reales del equipo y el contexto_diagnostico recibido.
    """
    cat = identificar_categoria_equipo(equipment)
    prob = resultado_ml.get("probabilidad_falla", 0.0)
    prob_pct = round(prob * 100, 1)
    m_actual = metricas_recientes[0] if metricas_recientes else None
    vib = _safe_float(m_actual.vibration_mm_s if m_actual else 5.2)
    temp = _safe_float(m_actual.temperature_celsius if m_actual else 78.0)

    if prob >= 0.70 or vib > 7.1 or (equipment.operational_status or "").lower() == "failed":
        prioridad: Literal["low", "medium", "high", "critical"] = "critical"
        freq_days = 0
        m_type = "Correctivo Inmediato (RCM)"
    elif prob >= 0.40 or vib >= 4.5:
        prioridad = "high"
        freq_days = 15
        m_type = "Predictivo Basado en Condición"
    else:
        prioridad = "medium"
        freq_days = 30
        m_type = "Preventivo Sistemático"

    ahora = datetime.now(timezone.utc)
    inicio_iso = ahora.strftime("%Y-%m-%dT%H:%M:%SZ")
    fin_iso = (ahora + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")

    if cat["is_tanque"]:
        tareas = [
            TareaMantenimientoSchema(
                title=f"Aislamiento LOTO y prueba de estanqueidad en {equipment.tag_number}",
                description=f"Bloqueo de líneas de proceso, despresurización y control de fugas en bridas de {equipment.name}.",
                category="inspection",
                estimated_duration_minutes=120,
                assigned_roles=["senior_technician", "safety_officer"],
                required_tools=["Detector multigás LEL/H2S", "Torquímetro 1/2 pulg 50-250 ft-lb", "Manómetro patrón"],
                required_parts=[RepuestoSchema(name="Empaquetadura espiralada ANSI 300", reference="GAR-300-SW", quantity=2)],
                instructions=[
                    "Aplicar LOTO y despresurizar línea de entrada/salida.",
                    "Sustituir empaquetadura afectada y aplicar torque cruzado.",
                    "Verificar presión de disparo de válvula PSV."
                ],
                safety_precautions=["LOTO Obligatorio", "Control de atmósfera explosiva LEL", "Uso de herramientas antichispa"]
            )
        ]
    else:
        tareas = [
            TareaMantenimientoSchema(
                title=f"Inspección mecánica, reemplazo de consumibles y alineación en {equipment.tag_number}",
                description=f"Intervención sobre rodamientos, sellos y alineación de eje ante lectura de {vib} mm/s RMS y {temp} °C.",
                category="replacement",
                estimated_duration_minutes=180,
                assigned_roles=["senior_technician", "field_technician"],
                required_tools=["Alineador láser de ejes", "Torquímetro 1/2 pulg 50-250 ft-lb", "Analizador de vibraciones FFT"],
                required_parts=[
                    RepuestoSchema(name="Kit de rodamientos y sellos de alta carga", reference="KIT-RCM-ROT", quantity=1),
                    RepuestoSchema(name="Lubricante sintético industrial ISO VG", reference="LUB-SYN-VG", quantity=2)
                ],
                instructions=[
                    "Ejecutar bloqueo LOTO y desacoplar transmisión.",
                    "Reemplazar elementos desgastados, lubricar y alinear con láser (< 0.05 mm).",
                    "Realizar prueba dinámica y medir vibración post-mantenimiento."
                ],
                safety_precautions=["Bloqueo y Etiquetado LOTO", "Análisis de Trabajo Seguro (ATS)", "Uso de EPP completo"]
            )
        ]

    horas_est = round(sum(t.estimated_duration_minutes for t in tareas) / 60.0, 1)

    return PlanMantenimientoIA(
        title=f"Plan de Intervención RCM - {equipment.tag_number}",
        maintenance_type=m_type,
        description=f"Plan generado con datos reales de {equipment.tag_number} ({equipment.name}) [Riesgo ML: {prob_pct}%]. Contexto: {contexto_diagnostico}",
        frequency_days=freq_days,
        priority=prioridad,
        estimated_hours=horas_est,
        schedule=CronogramaSchema(
            start_date=inicio_iso,
            end_date=fin_iso,
            intervals_days=freq_days if freq_days > 0 else 1
        ),
        tasks=tareas
    )


async def _persistir_recomendacion_segura(
    db: Optional[AsyncSession],
    payload_db: dict,
    notif_title: str,
    notif_msg: str,
    user_id: Optional[uuid.UUID] = None
):
    """
    Guarda la recomendación en `ai_recommendations` y emite la notificación `notify_ai_analysis_ready`
    en transacciones independientes sobre una sesión limpia para que ninguna bloquee a la otra.
    """
    rec = None
    async with AsyncSessionLocal() as sesion_limpia:
        try:
            rec = await crud_recommendation.create(sesion_limpia, payload_db)
            await sesion_limpia.commit()
            if rec:
                try:
                    await sesion_limpia.refresh(rec)
                except Exception:
                    pass
        except Exception as e:
            print(f"[ERROR DB RECOMENDACIÓN] Fallo guardando recomendación ({e}).")
            if db is not None:
                rec = await crud_recommendation.create(db, payload_db)
                await db.commit()

        # Disparar siempre la notificación en bloque separado para asegurar que llegue por BD, WebSocket y Push
        if rec:
            try:
                await notify_ai_analysis_ready(
                    db=sesion_limpia,
                    title=notif_title,
                    message=notif_msg,
                    user_id=user_id
                )
                await sesion_limpia.commit()
            except Exception as notif_err:
                print(f"[WARN NOTIFICACIÓN IA] Error con user_id={user_id}, reintentando global ({notif_err})...")
                try:
                    await notify_ai_analysis_ready(
                        db=sesion_limpia,
                        title=notif_title,
                        message=notif_msg,
                        user_id=None
                    )
                    await sesion_limpia.commit()
                except Exception as e2:
                    print(f"[ERROR NOTIFICACIÓN IA] No se pudo emitir la notificación: {e2}")

    return rec


# =====================================================================
# ENDPOINT INTERNO 1: ANÁLISIS PREDICTIVO DETALLADO POR EQUIPO (CAPA 2)
# =====================================================================
async def _ejecutar_analisis_predictivo_core(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    trigger_source: str,
    trigger_reference_id: uuid.UUID | None = None
) -> dict:
    """Núcleo del análisis predictivo sobre una sesión activa y verificada."""
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

    metrica_mas_reciente = metricas_recientes[0] if metricas_recientes else None
    es_disparo_anomalia = (trigger_reference_id is not None) or ("anomal" in (trigger_source or "").lower())
    hay_anomalia_fisica = _tiene_anomalia_fisica_directa(equipment, metrica_mas_reciente)
    hay_riesgo_ml = resultado_ml["probabilidad_falla"] >= 0.40

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
        f"MOTIVO DE DISPARO: {trigger_source}\n"
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
        "1. EXPLICACIÓN ML Y TELEMETRÍA: Recibes un diagnóstico probabilístico (%) y la última lectura de sensores. Explica físicamente la condición basándote en el salto temporal de la telemetría, umbrales normales, fallas previas y mantenimientos.\n"
        "2. CRITERIO DE INTERVENCIÓN: Si la probabilidad ML es >= 40% O si la última lectura registrada supera cualquiera de los 'Umbrales Normales Operativos', SIEMPRE establece `requiere_intervencion = true` y asigna el `prediction_type` de riesgo correspondiente. Solo establece `requiere_intervencion = false` cuando TANTO el ML (<40%) COMO todos los sensores estén dentro de rango normal.\n"
        "3. HISTORIAL DE CORRECCIONES: Lee atentamente las correcciones de los expertos.\n"
        "4. CRITICIDAD E IMPACTO: Si detectas anomalía real, revisa los puntajes de Seguridad o Ambiental para incluir contenciones preventivas urgentes en tu plan de acción.\n"
        "5. CORRELACIÓN HISTÓRICA: Usa el 'Historial de Fallas' y 'Historial de Mantenimientos' para justificar tus hipótesis."
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
    except Exception as e:
        print(f"[ADVERTENCIA IA] Fallo en análisis predictivo Gemini ({e}). Ejecutando consulta de contingencia con los mismos datos del equipo...")
        resultado_obj = _generar_informe_contingencia_mismos_datos(
            equipment=equipment,
            criticality=criticality,
            metricas_recientes=metricas_recientes,
            ultimas_fallas=ultimas_fallas,
            ultimos_mantenimientos=ultimos_mantenimientos,
            resultado_ml=resultado_ml,
            forzar_intervencion=(es_disparo_anomalia or hay_anomalia_fisica or hay_riesgo_ml)
        )

    # Si fue disparado por una métrica anómala real, o el ML es >= 40%, o supera standard_metric, asegurar que se guarde
    if es_disparo_anomalia or hay_riesgo_ml or hay_anomalia_fisica:
        resultado_obj.requiere_intervencion = True
        if resultado_obj.prediction_type == "Operación Normal":
            resultado_obj.prediction_type = "Inspección Basada en Condición (CBM)"

    resultado_dict = resultado_obj.model_dump()
    resultado_dict["probabilidad_ml"] = resultado_ml["probabilidad_falla"]

    # 7. GENERACIÓN DEL REPORTE TEXTUAL Y GUARDADO SOLO SI TIENE PROBABILIDAD DE FALLAR / ANOMALÍA
    recomendacion_creada = None

    if resultado_obj.requiere_intervencion:
        prob_pct = round(resultado_ml["probabilidad_falla"] * 100, 1)
        confianza_pct = int(resultado_obj.confianza * 100)
        normas_str = ", ".join(resultado_obj.normas_aplicadas) if resultado_obj.normas_aplicadas else "ISO 14224, SAE JA1011"
        plan_accion_str = "\n".join([f"  {i}. {accion}" for i, accion in enumerate(resultado_obj.plan_accion, start=1)])

        informe_texto = (
            f"▸ Dictamen Técnico: {resultado_obj.diagnostico_principal}\n"
            f"▸ Riesgo Estadístico ML (<48h): {prob_pct}% ({resultado_ml['clasificacion_alerta']})  |  Certeza IA: {confianza_pct}%\n"
            f"──────────────────────────────────────────────────\n\n"
            f"1. Evaluación de Condición y Correlación Histórica:\n"
            f"{resultado_obj.evaluacion_condicion}\n\n"
            f"2. Hipótesis de Causa Raíz (Explicación Física):\n"
            f"{resultado_obj.hipotesis_causa_raiz}\n\n"
            f"3. Plan de Acción Inmediato en Campo:\n"
            f"{plan_accion_str}\n\n"
            f"4. Normas y Principios Aplicados:\n"
            f"• {normas_str}"
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

        target_user_id = getattr(metrica_mas_reciente, "recorded_by", None) or getattr(equipment, "created_by", None)

        recomendacion_creada = await _persistir_recomendacion_segura(
            db=db,
            payload_db=payload_db,
            notif_title="🧠 Análisis Predictivo IA Listo",
            notif_msg=f"La IA ha generado un dictamen técnico de riesgo ({prob_pct}%) para el equipo {equipment.tag_number}.",
            user_id=target_user_id
        )

    return {
        "analisis_ia": resultado_dict, 
        "recomendacion_generada": recomendacion_creada is not None,
        "detalle_recomendacion": recomendacion_creada
    }


async def ejecutar_analisis_predictivo_ia(
    db: Optional[AsyncSession], 
    equipment_id: uuid.UUID, 
    trigger_source: str, 
    trigger_reference_id: uuid.UUID | None = None
) -> dict:
    """
    Punto de entrada principal para análisis predictivo.
    Si es llamado desde un BackgroundTask (ej. cuando `trigger_reference_id` está presente o `db` es None),
    abre siempre una sesión independiente con `AsyncSessionLocal()` para evitar sesiones huérfanas/cerradas.
    """
    if db is None or trigger_reference_id is not None:
        async with AsyncSessionLocal() as bg_db:
            return await _ejecutar_analisis_predictivo_core(
                db=bg_db,
                equipment_id=equipment_id,
                trigger_source=trigger_source,
                trigger_reference_id=trigger_reference_id
            )

    return await _ejecutar_analisis_predictivo_core(
        db=db,
        equipment_id=equipment_id,
        trigger_source=trigger_source,
        trigger_reference_id=trigger_reference_id
    )


async def ejecutar_analisis_predictivo_background(
    equipment_id: uuid.UUID,
    trigger_source: str,
    trigger_reference_id: uuid.UUID | None = None
) -> dict:
    """
    Función dedicada para `background_tasks.add_task(...)` en `services/equipment_metrics.py`.
    No recibe la sesión del request HTTP sino que crea su propia `AsyncSessionLocal`.
    """
    async with AsyncSessionLocal() as bg_db:
        return await _ejecutar_analisis_predictivo_core(
            db=bg_db,
            equipment_id=equipment_id,
            trigger_source=trigger_source,
            trigger_reference_id=trigger_reference_id
        )


# =====================================================================
# ENDPOINT INTERNO 1-B: RUTA DIRECTA DE CONTINGENCIA (SOLO GUARDA SI HAY RIESGO)
# =====================================================================
async def ejecutar_analisis_predictivo_fallback(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    trigger_source: str,
    trigger_reference_id: uuid.UUID | None = None
) -> dict:
    """
    Ruta de contingencia directa que toma los mismos datos reales del equipo y del modelo ML.
    SOLO guarda la recomendación en PostgreSQL si existe probabilidad de falla / requiere intervención.
    """
    equipment = (await db.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one_or_none()
    if not equipment:
        return {"analisis_ia": None, "error": "Equipo no encontrado", "recomendacion_generada": False}

    criticality = (await db.execute(select(EquipmentCriticality).where(EquipmentCriticality.equipment_id == equipment_id))).scalar_one_or_none()
    metricas_recientes = (await db.execute(
        select(EquipmentMetricHistory).where(EquipmentMetricHistory.equipment_id == equipment_id).order_by(EquipmentMetricHistory.recorded_at.desc()).limit(50)
    )).scalars().all()
    ultimas_fallas = (await db.execute(
        select(FailureHistory).where(FailureHistory.equipment_id == equipment_id).order_by(FailureHistory.failure_date.desc()).limit(5)
    )).scalars().all()
    ultimos_mantenimientos = (await db.execute(
        select(MaintenanceHistory).where(MaintenanceHistory.equipment_id == equipment_id).order_by(MaintenanceHistory.execution_date.desc()).limit(5)
    )).scalars().all()

    resultado_ml = evaluar_metrica_actual_ml(
        equipment=equipment,
        metricas_orm=metricas_recientes,
        ultimas_fallas=ultimas_fallas,
        ultimos_mantenimientos=ultimos_mantenimientos
    )

    es_disparo_anomalia = (trigger_reference_id is not None) or ("anomal" in (trigger_source or "").lower())

    resultado_obj = _generar_informe_contingencia_mismos_datos(
        equipment=equipment,
        criticality=criticality,
        metricas_recientes=metricas_recientes,
        ultimas_fallas=ultimas_fallas,
        ultimos_mantenimientos=ultimos_mantenimientos,
        resultado_ml=resultado_ml,
        forzar_intervencion=es_disparo_anomalia
    )

    resultado_dict = resultado_obj.model_dump()
    resultado_dict["probabilidad_ml"] = resultado_ml["probabilidad_falla"]

    recomendacion_creada = None

    if resultado_obj.requiere_intervencion:
        prob_pct = round(resultado_ml["probabilidad_falla"] * 100, 1)
        confianza_pct = int(resultado_obj.confianza * 100)
        normas_str = ", ".join(resultado_obj.normas_aplicadas)
        plan_accion_str = "\n".join([f"  {i}. {accion}" for i, accion in enumerate(resultado_obj.plan_accion, start=1)])

        informe_texto = (
            f"▸ Dictamen Técnico: {resultado_obj.diagnostico_principal}\n"
            f"▸ Riesgo Estadístico ML (<48h): {prob_pct}% ({resultado_ml['clasificacion_alerta']})  |  Certeza IA: {confianza_pct}%\n"
            f"──────────────────────────────────────────────────\n\n"
            f"1. Evaluación de Condición y Correlación Histórica:\n"
            f"{resultado_obj.evaluacion_condicion}\n\n"
            f"2. Hipótesis de Causa Raíz (Explicación Física):\n"
            f"{resultado_obj.hipotesis_causa_raiz}\n\n"
            f"3. Plan de Acción Inmediato en Campo:\n"
            f"{plan_accion_str}\n\n"
            f"4. Normas y Principios Aplicados:\n"
            f"• {normas_str}"
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

        metrica_mas_reciente = metricas_recientes[0] if metricas_recientes else None
        target_user_id = getattr(metrica_mas_reciente, "recorded_by", None) or getattr(equipment, "created_by", None)

        recomendacion_creada = await _persistir_recomendacion_segura(
            db=db,
            payload_db=payload_db,
            notif_title="🧠 Análisis Predictivo IA Listo",
            notif_msg=f"La IA ha generado un dictamen técnico de riesgo ({prob_pct}%) para el equipo {equipment.tag_number}.",
            user_id=target_user_id
        )

    return {
        "analisis_ia": resultado_dict,
        "recomendacion_generada": recomendacion_creada is not None,
        "detalle_recomendacion": recomendacion_creada
    }


# =====================================================================
# ENDPOINT INTERNO 2: GENERACIÓN DE PLAN DE MANTENIMIENTO (SIEMPRE SE GUARDA)
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
    SIEMPRE guarda el plan en la tabla de recomendaciones y envía notificación.
    """
    equipment = (await db.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one_or_none()
    if not equipment:
        return {"plan_generado": None, "error": "Equipo no encontrado", "recomendacion_generada": False}

    metricas_recientes = (await db.execute(
        select(EquipmentMetricHistory).where(EquipmentMetricHistory.equipment_id == equipment_id).order_by(EquipmentMetricHistory.recorded_at.desc()).limit(50)
    )).scalars().all()
    ultimas_fallas = (await db.execute(
        select(FailureHistory).where(FailureHistory.equipment_id == equipment_id).order_by(FailureHistory.failure_date.desc()).limit(5)
    )).scalars().all()
    ultimos_mantenimientos = (await db.execute(
        select(MaintenanceHistory).where(MaintenanceHistory.equipment_id == equipment_id).order_by(MaintenanceHistory.execution_date.desc()).limit(5)
    )).scalars().all()

    resultado_ml = evaluar_metrica_actual_ml(
        equipment=equipment,
        metricas_orm=metricas_recientes,
        ultimas_fallas=ultimas_fallas,
        ultimos_mantenimientos=ultimos_mantenimientos
    )

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
    except Exception as e:
        print(f"[ADVERTENCIA IA] Fallo generando plan en Gemini ({e}). Ejecutando plan de contingencia con los mismos datos del equipo...")
        plan_obj = _generar_plan_contingencia_mismos_datos(
            equipment=equipment,
            contexto_diagnostico=contexto_diagnostico,
            metricas_recientes=metricas_recientes,
            resultado_ml=resultado_ml
        )

    plan_dict = plan_obj.model_dump()

    prioridad_es = TRADUCCION_PRIORIDAD.get(plan_obj.priority.lower(), plan_obj.priority.capitalize())
    frecuencia_str = "Inmediata (Emergencia)" if plan_obj.frequency_days == 0 else f"Cada {plan_obj.frequency_days} días"

    texto_plan = (
        f"▸ Plan Propuesto: {plan_obj.title}\n"
        f"▸ Estrategia: {plan_obj.maintenance_type}  |  Prioridad: {prioridad_es}\n"
        f"▸ Frecuencia: {frecuencia_str}  |  Duración Estimada: {plan_obj.estimated_hours} hrs\n"
        f"──────────────────────────────────────────────────\n\n"
        f"Justificación Técnica:\n"
        f"{plan_obj.description}\n\n"
        f"Desglose de Tareas Principales ({len(plan_obj.tasks)}):\n\n"
    )

    for i, tarea in enumerate(plan_obj.tasks, start=1):
        categoria_es = TRADUCCION_CATEGORIA.get(tarea.category.lower(), tarea.category.capitalize())
        roles_es = _formatear_roles(tarea.assigned_roles)
        repuestos_str = ", ".join([f"{p.name} (x{p.quantity})" for p in tarea.required_parts]) if tarea.required_parts else "Sin repuestos requeridos"
        seguridad_str = " | ".join(tarea.safety_precautions) if tarea.safety_precautions else "LOTO y EPP estándar"

        texto_plan += (
            f"{i}. {tarea.title} ({categoria_es} — {tarea.estimated_duration_minutes} min)\n"
            f"   • Descripción: {tarea.description}\n"
            f"   • Especialidades: {roles_es}\n"
            f"   • Repuestos de Bodega: {repuestos_str}\n"
            f"   • Seguridad y HSE: {seguridad_str}\n\n"
        )

    payload_db = {
        "equipment_id": equipment_id,
        "trigger_source": trigger_source,
        "trigger_reference_id": None, 
        "recommendation_text": texto_plan.strip(),
        "confidence_score": 0.95, 
        "prediction_type": "Plan Preventivo/Predictivo (IA Generativa)", 
        "status": "Pendiente"
    }

    target_user_id = getattr(equipment, "created_by", None)

    recomendacion_creada = await _persistir_recomendacion_segura(
        db=db,
        payload_db=payload_db,
        notif_title="📋 Plan de Mantenimiento IA Estructurado",
        notif_msg=f"Se ha estructurado un plan '{plan_obj.title}' para el equipo {equipment.tag_number}.",
        user_id=target_user_id
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
# ENDPOINT INTERNO 2-B: RUTA DIRECTA DE PLAN EN CONTINGENCIA (SIEMPRE SE GUARDA)
# =====================================================================
async def generar_plan_mantenimiento_fallback(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    contexto_diagnostico: str,
    trigger_source: str = "Asistente IA - Generación de Plan (Contingencia)"
) -> dict:
    """Genera y guarda siempre el plan de mantenimiento directamente con los datos del equipo sin llamar a Gemini."""
    equipment = (await db.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one_or_none()
    if not equipment:
        return {"plan_generado": None, "error": "Equipo no encontrado", "recomendacion_generada": False}

    metricas_recientes = (await db.execute(
        select(EquipmentMetricHistory).where(EquipmentMetricHistory.equipment_id == equipment_id).order_by(EquipmentMetricHistory.recorded_at.desc()).limit(50)
    )).scalars().all()
    ultimas_fallas = (await db.execute(
        select(FailureHistory).where(FailureHistory.equipment_id == equipment_id).order_by(FailureHistory.failure_date.desc()).limit(5)
    )).scalars().all()
    ultimos_mantenimientos = (await db.execute(
        select(MaintenanceHistory).where(MaintenanceHistory.equipment_id == equipment_id).order_by(MaintenanceHistory.execution_date.desc()).limit(5)
    )).scalars().all()

    resultado_ml = evaluar_metrica_actual_ml(
        equipment=equipment,
        metricas_orm=metricas_recientes,
        ultimas_fallas=ultimas_fallas,
        ultimos_mantenimientos=ultimos_mantenimientos
    )

    plan_obj = _generar_plan_contingencia_mismos_datos(
        equipment=equipment,
        contexto_diagnostico=contexto_diagnostico,
        metricas_recientes=metricas_recientes,
        resultado_ml=resultado_ml
    )
    plan_dict = plan_obj.model_dump()

    prioridad_es = TRADUCCION_PRIORIDAD.get(plan_obj.priority.lower(), plan_obj.priority.capitalize())
    frecuencia_str = "Inmediata (Emergencia)" if plan_obj.frequency_days == 0 else f"Cada {plan_obj.frequency_days} días"

    texto_plan = (
        f"▸ Plan Propuesto: {plan_obj.title}\n"
        f"▸ Estrategia: {plan_obj.maintenance_type}  |  Prioridad: {prioridad_es}\n"
        f"▸ Frecuencia: {frecuencia_str}  |  Duración Estimada: {plan_obj.estimated_hours} hrs\n"
        f"──────────────────────────────────────────────────\n\n"
        f"Justificación Técnica:\n"
        f"{plan_obj.description}\n\n"
        f"Desglose de Tareas Principales ({len(plan_obj.tasks)}):\n\n"
    )

    for i, tarea in enumerate(plan_obj.tasks, start=1):
        categoria_es = TRADUCCION_CATEGORIA.get(tarea.category.lower(), tarea.category.capitalize())
        roles_es = _formatear_roles(tarea.assigned_roles)
        repuestos_str = ", ".join([f"{p.name} (x{p.quantity})" for p in tarea.required_parts]) if tarea.required_parts else "Sin repuestos requeridos"
        seguridad_str = " | ".join(tarea.safety_precautions) if tarea.safety_precautions else "LOTO y EPP estándar"

        texto_plan += (
            f"{i}. {tarea.title} ({categoria_es} — {tarea.estimated_duration_minutes} min)\n"
            f"   • Descripción: {tarea.description}\n"
            f"   • Especialidades: {roles_es}\n"
            f"   • Repuestos de Bodega: {repuestos_str}\n"
            f"   • Seguridad y HSE: {seguridad_str}\n\n"
        )

    payload_db = {
        "equipment_id": equipment_id,
        "trigger_source": trigger_source,
        "trigger_reference_id": None,
        "recommendation_text": texto_plan.strip(),
        "confidence_score": 0.95,
        "prediction_type": "Plan Preventivo/Predictivo (IA Generativa)",
        "status": "Pendiente"
    }

    target_user_id = getattr(equipment, "created_by", None)

    recomendacion_creada = await _persistir_recomendacion_segura(
        db=db,
        payload_db=payload_db,
        notif_title="📋 Plan de Mantenimiento IA Estructurado",
        notif_msg=f"Se ha estructurado un plan '{plan_obj.title}' para el equipo {equipment.tag_number}.",
        user_id=target_user_id
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