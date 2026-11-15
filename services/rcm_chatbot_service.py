"""
services/rcm_chatbot_service.py
Servicio Central del Asistente Conversacional RCM (Chatbot) con Inteligencia Artificial.
Inspirado en la arquitectura modular de maxton_ai_back (BeautyAdvisorService / Controller)
y adaptado al dominio de Mantenimiento Centrado en Confiabilidad (SAE JA1011, ISO 14224 e ISO 10816-3).
Soporta creación física de Órdenes de Trabajo y Planes de Mantenimiento en PostgreSQL,
propuestas de acción con 1 clic (Action Proposals), dossiers técnicos exhaustivos por activo,
detección de Equipos Críticos (operational_status == 'failed', Clase A y RPN) y Equipos con
Probabilidad de Falla (>= 40% en Modelo ML XGBoost + RPM y telemetría en vivo).
"""

import os
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

from models.equipment import Equipment
from models.equipment_metrics import EquipmentMetricHistory
from models.fmea_analysis import FMEAAnalysis
from models.equipment_criticality import EquipmentCriticality
from models.failure_history import FailureHistory
from models.maintenance_history import MaintenanceHistory
from models.ai_recommendation import AIRecommendation
from models.ai_correction import AICorrection
from models.maintenance import Maintenance
from models.work_orders import WorkOrder
from models.user import User

# Integración directa con la Capa 1 (Machine Learning XGBoost) y Radar Global de Planta
from services.ai_predictive_service import (
    evaluar_metrica_actual_ml,
    evaluar_riesgo_global_planta,
    _safe_float,
)

logger = logging.getLogger("rcm_chatbot")

# Modelos candidatos en orden de prioridad para cascada de alta disponibilidad (INTACTOS)
CANDIDATE_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-2.5-pro",
]

# Diccionario de alias entre tags de tesis/usuario y tags físicos existentes en PostgreSQL
TAG_ALIASES = {
    "CMP-001": "K-201A",
    "CMP 001": "K-201A",
    "COMPRESOR-001": "K-201A",
    "POZO-BCP-204": "P-501A",
    "BCP-204": "P-501A",
    "BCP 204": "P-501A",
    "POZO 204": "P-501A",
    "POZO-BES-512": "P-601",
    "BES-512": "P-601",
    "BES 512": "P-601",
    "POZO 512": "P-601",
    "BOM-DCO-102": "P-401A",
    "DCO-102": "P-401A",
    "BOMBA-102": "P-401A",
    "SEP-TRI-301": "TK-103",
    "TRI-301": "TK-103",
    "SEPARADOR-301": "TK-103",
    "GEN-CAT-401": "K-301",
    "CAT-401": "K-301",
    "GENERADOR-401": "K-301",
    "BOM-AGU-205": "BOMBA-CENTRIFUGA-01",
    "AGU-205": "BOMBA-CENTRIFUGA-01",
    "TUR-EXP-101": "K-302",
    "EXP-101": "K-302",
}


class RcmChatbotService:
    """
    Servicio de Asesoría Técnica RCM y Diagnóstico Predictivo Inteligente.
    Gestiona el contexto conversacional, análisis multimodal (imágenes de componentes/placas),
    inyección de telemetría de activos en tiempo real desde PostgreSQL, inferencia ML (XGBoost),
    radar global de planta y listado de equipos críticos (failed / Clase A / RPN) y con probabilidad
    de falla (>= 40% ML + RPM), generación de órdenes de trabajo físicas y planes de mantenimiento.
    """

    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning("[RCM CHATBOT] GEMINI_API_KEY no encontrada en variables de entorno.")
            self.client = None
        else:
            try:
                self.client = genai.Client(api_key=self.api_key)
                logger.info("[RCM CHATBOT] Cliente Google GenAI inicializado correctamente.")
            except Exception as e:
                logger.error(f"[RCM CHATBOT] Error inicializando cliente GenAI: {e}")
                self.client = None

        # Historial de conversaciones en memoria: session_id -> List[dict]
        self.conversations: Dict[str, List[dict]] = {}
        self.system_prompt = self._get_system_prompt()

    def _get_system_prompt(self) -> str:
        return (
            "Eres el Asistente de Inteligencia Artificial de Heimdall RCM, especializado en "
            "Mantenimiento Centrado en Confiabilidad (SAE JA1011), Taxonomía Petrolera (ISO 14224), "
            "Severidad de Vibraciones Mecánicas (ISO 10816-3), Diagnóstico Predictivo con Machine Learning (XGBoost) "
            "y Gestión de Activos Industriales.\n\n"
            "TUS FUNCIONES Y CAPACIDADES PRINCIPALES:\n"
            "1. Responder dudas metodológicas sobre RCM y las 7 preguntas de la norma SAE JA1011.\n"
            "2. Explicar el análisis de modos y efectos de falla (AMEF / FMEA) y el cálculo del Número de Prioridad de Riesgo (RPN = S x O x D).\n"
            "3. Evaluar la severidad de vibraciones bajo ISO 10816-3:\n"
            "   - Zona A (<2.8 mm/s RMS): Condición excelente de maquinaria nueva o reparada.\n"
            "   - Zona B (2.8 - 4.5 mm/s RMS): Operación normal admisible sin restricciones.\n"
            "   - Zona C (4.5 - 7.1 mm/s RMS): Alerta preventiva, deterioro incipiente, planificar intervención.\n"
            "   - Zona D (>7.1 mm/s RMS): Daño inminente, alarma crítica, parada obligatoria de inmediato.\n"
            "4. DISTINCIÓN ESTRICTA ENTRE 'EQUIPOS CRÍTICOS' Y 'EQUIPOS CON PROBABILIDAD DE FALLA':\n"
            "   a) CUANDO PIDAN 'EQUIPOS CRÍTICOS':\n"
            "      - Todo equipo cuyo `operational_status` sea `'failed'` (en falla) ES AUTOMÁTICAMENTE CRÍTICO PRIORIDAD 1.\n"
            "      - También son críticos los equipos con Criticidad RCM Clase A / Crítico o RPN >= 200.\n"
            "      - Debes listar su TAG, Nombre, Estado Operativo (`failed` / `operational` / `maintenance`), Nivel de Criticidad RCM, RPN score y sus RPM.\n"
            "   b) CUANDO PIDAN 'EQUIPOS CON PROBABILIDAD DE FALLA' (O RIESGO DE DAÑARSE):\n"
            "      - Debes filtrar y destacar los equipos cuya Probabilidad de Falla en el modelo Machine Learning (XGBoost) sea >= 40% (Alerta MODERADA >=40% o CRÍTICA >=70%).\n"
            "      - Incluye siempre el porcentaje exacto de probabilidad de falla del modelo ML, el RPN, las RPM (`velocidad_rpm`), la vibración (mm/s), la temperatura (°C) y el salto de amperaje.\n"
            "5. CREACIÓN DIRECTA DE ÓRDENES DE TRABAJO Y PLANES:\n"
            "   Tienes la capacidad de crear físicamente Órdenes de Trabajo (OT) y Planes de Mantenimiento en la base de datos PostgreSQL.\n"
            "   Cuando el usuario te pida crear una OT o plan (ej. 'crea una orden de trabajo para K-201A por vibración alta'), confirma que la acción ha sido procesada.\n\n"
            "6. CUANDO SE CONSULTE POR UN ACTIVO O MAQUINARIA ESPECÍFICA:\n"
            "   DEBES EMITIR UN DOSSIER TÉCNICO DE INGENIERÍA EXHAUSTIVO Y DETALLADO ESTRUCTURADO EN 6 SECCIONES:\n"
            "   1. Ficha Técnica y Taxonomía del Activo (ISO 14224): TAG, nombre, clasificación, fabricante, modelo, estado operativo (`failed` = Crítico en falla) y función primaria según SAE JA1011.\n"
            "   2. Telemetría de Sensores, Predicción ML (XGBoost) y Condición en Tiempo Real: Probabilidad de falla inminente (<48h) en %, clasificación de alerta ML, velocidad de giro (RPM), salto de amperaje, vibración RMS en mm/s evaluada contra Zona A/B/C/D de ISO 10816-3, temperatura (°C), horas acumuladas y variables de proceso.\n"
            "   3. Jerarquía de Criticidad, Historial Operativo y Matriz de Riesgo: Clase A/B/C, RPN score, días desde última falla, días desde último mantenimiento y eventos previos.\n"
            "   4. Análisis AMEF de Modos de Falla Dominantes (SAE JA1011): Modos de falla específicos según la tecnología del activo, causas raíz y consecuencias funcionales.\n"
            "   5. Estrategia y Acciones Prescriptivas RCM: Procedimientos técnicos paso a paso (alineación láser, lubricación con especificación, boroscopia, análisis FFT).\n"
            "   6. Propuesta de Acción Inmediata: Sugerencia concreta para emitir Orden de Trabajo o Plan Preventivo.\n\n"
            "DIRECTRICES DE COMUNICACIÓN:\n"
            "- Responde en español técnico, riguroso, formal y profesional.\n"
            "- NUNCA utilices emojis en telemetría técnica, diagnósticos ni reportes de alarma industrial.\n"
            "- Utiliza siempre los datos reales de estado (`operational_status`), RPM, RPN, predicción ML (XGBoost >= 40%), telemetría e historial provistos en el contexto de base de datos.\n"
            "- Si existen correcciones humanas previas en el contexto que desestimen una alerta similar, respétalas.\n"
            "- Si el usuario envía una imagen, analiza si corresponde a una chapa técnica (extrae TAG, RPM, potencia), a una pieza con falla física o a un espectro de vibración."
        )

    def _extract_rpm(self, specific_metrics: Optional[dict], tech_specs: Optional[dict]) -> float:
        """Extrae las RPM del activo desde las métricas específicas del sensor o las especificaciones técnicas."""
        specs = specific_metrics or {}
        t_specs = tech_specs or {}
        std_metric = t_specs.get("standard_metric") if isinstance(t_specs.get("standard_metric"), dict) else {}

        rpm_val = (
            specs.get("velocidad_rpm")
            or specs.get("rpm")
            or specs.get("RPM")
            or specs.get("Velocidad (RPM)")
            or t_specs.get("velocidad_rpm")
            or t_specs.get("rpm")
            or t_specs.get("RPM")
            or std_metric.get("velocidad_rpm")
            or std_metric.get("rpm")
            or 0.0
        )
        return _safe_float(rpm_val, 0.0)

    def _is_failed_status(self, status: Optional[str]) -> bool:
        """Verifica si el operational_status del equipo indica que está en falla ('failed')."""
        if not status:
            return False
        s_low = status.strip().lower()
        return s_low in ["failed", "falla", "en falla", "critical", "critico", "crítico", "out_of_service", "fuera de servicio", "down"]

    async def get_default_user_id(self, db: AsyncSession, user_id: Optional[uuid.UUID] = None) -> uuid.UUID:
        """Obtiene un ID de usuario válido para trazabilidad de creación física."""
        if user_id:
            return user_id
        try:
            q = select(User.id).where(User.is_active == True).limit(1)
            res = await db.execute(q)
            uid = res.scalars().first()
            if uid:
                return uid
        except Exception as e:
            logger.warning(f"[RCM CHATBOT] No se pudo obtener usuario de BD ({e}), usando UUID por defecto.")
        return uuid.UUID("51bb07ab-7059-4fc6-afa0-54020251955a")

    async def get_plant_global_context(self, db: AsyncSession) -> Optional[Dict[str, Any]]:
        """
        Obtiene el inventario completo de máquinas activas en la planta cruzando:
        1. Estado operativo (`operational_status == 'failed'` -> Crítico directo).
        2. Jerarquía de Criticidad RCM (`EquipmentCriticality`: Clase A/B/C y `rpn_score`).
        3. Probabilidad de falla del modelo Machine Learning XGBoost (`>= 40%`) y RPM (`velocidad_rpm`).
        4. Telemetría actual (vibración, temperatura, amperaje).
        """
        if not db:
            return None
        try:
            resumen_riesgo = await evaluar_riesgo_global_planta(db)

            equipos_q = select(Equipment).where(
                Equipment.is_active == True,
                Equipment.deleted_at.is_(None)
            ).order_by(Equipment.tag_number.asc())
            equipos_orm = (await db.execute(equipos_q)).scalars().all()

            # Cargar todas las criticidades en un diccionario para cruce rápido O(1)
            crit_q = select(EquipmentCriticality)
            crit_rows = (await db.execute(crit_q)).scalars().all()
            crit_map = {c.equipment_id: c for c in crit_rows}

            inventario_completo = []
            equipos_criticos_planta = []      # Equipos con status == 'failed', Clase A o RPN >= 200
            equipos_en_falla_status = []      # Equipos específicamente con operational_status == 'failed'
            equipos_probabilidad_ml = []      # Equipos con probabilidad de falla ML >= 40%

            for eq in equipos_orm:
                metricas_q = (
                    select(EquipmentMetricHistory)
                    .where(EquipmentMetricHistory.equipment_id == eq.id)
                    .order_by(desc(EquipmentMetricHistory.recorded_at))
                    .limit(50)
                )
                metricas_recientes = (await db.execute(metricas_q)).scalars().all()

                fallas_q = (
                    select(FailureHistory)
                    .where(FailureHistory.equipment_id == eq.id)
                    .order_by(desc(FailureHistory.failure_date))
                    .limit(5)
                )
                ultimas_fallas = (await db.execute(fallas_q)).scalars().all()

                maint_q = (
                    select(MaintenanceHistory)
                    .where(MaintenanceHistory.equipment_id == eq.id)
                    .order_by(desc(MaintenanceHistory.execution_date))
                    .limit(5)
                )
                ultimos_mantenimientos = (await db.execute(maint_q)).scalars().all()

                ml_eval = evaluar_metrica_actual_ml(
                    equipment=eq,
                    metricas_orm=metricas_recientes,
                    ultimas_fallas=ultimas_fallas,
                    ultimos_mantenimientos=ultimos_mantenimientos
                )

                crit_obj = crit_map.get(eq.id)
                crit_level = crit_obj.criticality_level if crit_obj and crit_obj.criticality_level else "Clase B (Semicrítico)"
                rpn_score = int(crit_obj.rpn_score) if crit_obj and crit_obj.rpn_score is not None else 160

                ultima_m = metricas_recientes[0] if metricas_recientes else None
                specific_m = ultima_m.specific_metrics if ultima_m and ultima_m.specific_metrics else {}
                tech_specs = eq.technical_specifications if eq.technical_specifications else {}

                rpm_actual = self._extract_rpm(specific_m, tech_specs)
                vib_actual = float(ultima_m.vibration_mm_s) if ultima_m and ultima_m.vibration_mm_s is not None else None
                temp_actual = float(ultima_m.temperature_celsius) if ultima_m and ultima_m.temperature_celsius is not None else None
                prob_pct = round(ml_eval["probabilidad_falla"] * 100, 2)

                status_raw = eq.operational_status or "operational"
                is_failed = self._is_failed_status(status_raw)

                crit_upper = crit_level.upper()
                es_clase_a = (
                    ("CLASE A" in crit_upper)
                    or ("ALTA" in crit_upper)
                    or ("HIGH" in crit_upper)
                    or ("CRÍTICO" in crit_upper and "SEMICRÍTICO" not in crit_upper and "NO CRÍTICO" not in crit_upper)
                    or ("CRITICO" in crit_upper and "SEMICRITICO" not in crit_upper and "NO CRITICO" not in crit_upper)
                    or (rpn_score >= 200)
                )

                # Regla 1: Es Equipo Crítico si su status es 'failed', o si es Clase A / RPN >= 200, o si su alerta ML es CRÍTICA (>=70%)
                es_equipo_critico = is_failed or es_clase_a or (prob_pct >= 70.0)

                # Regla 2: Tiene Probabilidad de Falla si el modelo ML arroja >= 40%
                tiene_prob_falla_ml = prob_pct >= 40.0

                motivo_criticidad = []
                if is_failed:
                    motivo_criticidad.append("ESTADO OPERATIVO: FAILED (EN FALLA)")
                if es_clase_a:
                    motivo_criticidad.append(f"MATRIZ RCM: {crit_level} (RPN {rpn_score})")
                if prob_pct >= 70.0:
                    motivo_criticidad.append(f"ALERTA ML CRÍTICA ({prob_pct}%)")

                item_data = {
                    "id": str(eq.id),
                    "tag_number": eq.tag_number,
                    "name": eq.name,
                    "equipment_type": eq.equipment_type,
                    "operational_status": status_raw,
                    "is_failed_status": is_failed,
                    "criticality_level": "CRÍTICO (FAILED)" if is_failed and not es_clase_a else crit_level,
                    "rpn_score": rpn_score,
                    "velocidad_rpm": rpm_actual,
                    "es_critico": es_equipo_critico,
                    "motivos_criticidad": " | ".join(motivo_criticidad) if motivo_criticidad else "Operación Estándar",
                    "tiene_probabilidad_falla_40": tiene_prob_falla_ml,
                    "probabilidad_falla_pct": prob_pct,
                    "clasificacion_alerta_ml": ml_eval["clasificacion_alerta"],
                    "salto_amperaje": ml_eval["salto_amperaje"],
                    "vibration_mm_s": vib_actual,
                    "temperature_celsius": temp_actual,
                    "dias_ultima_falla": ml_eval["dias_ultima_falla"],
                    "dias_ultimo_mantenimiento": ml_eval["dias_ultimo_mantenimiento"],
                }

                inventario_completo.append(item_data)
                if is_failed:
                    equipos_en_falla_status.append(item_data)
                if es_equipo_critico:
                    equipos_criticos_planta.append(item_data)
                if tiene_prob_falla_ml:
                    equipos_probabilidad_ml.append(item_data)

            # Ordenar equipos críticos priorizando primero los que tienen status == 'failed', luego RPN y probabilidad ML
            equipos_criticos_planta.sort(
                key=lambda x: (1 if x["is_failed_status"] else 0, x["probabilidad_falla_pct"], x["rpn_score"]),
                reverse=True
            )
            # Ordenar equipos con probabilidad de falla (>=40% ML) de mayor a menor probabilidad
            equipos_probabilidad_ml.sort(
                key=lambda x: (x["probabilidad_falla_pct"], x["rpn_score"]),
                reverse=True
            )
            inventario_completo.sort(
                key=lambda x: (1 if x["is_failed_status"] else 0, x["probabilidad_falla_pct"], x["rpn_score"]),
                reverse=True
            )

            return {
                "total_analizados": resumen_riesgo.get("total_analizados", len(inventario_completo)),
                "equipos_sanos": resumen_riesgo.get("equipos_sanos", 0),
                "equipos_failed_count": len(equipos_en_falla_status),
                "equipos_criticos_count": len(equipos_criticos_planta),
                "equipos_en_riesgo_ml_count": len(equipos_probabilidad_ml),
                "alertas_criticas": resumen_riesgo.get("alertas", []),
                "equipos_failed": equipos_en_falla_status,
                "equipos_criticos_planta": equipos_criticos_planta,
                "equipos_probabilidad_ml": equipos_probabilidad_ml,
                "inventario_planta": inventario_completo,
            }
        except Exception as e:
            logger.error(f"[RCM CHATBOT] Error obteniendo contexto global de planta: {e}")
            return None

    async def get_equipment_db_context(self, db: AsyncSession, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Recupera información técnica, estado (`failed`), RPM, últimas 50 métricas de sensores,
        predicción ML (XGBoost), historial de fallas, mantenimientos ejecutados, correcciones humanas y AMEFs
        asociados a un TAG o UUID de equipo desde PostgreSQL.
        """
        if not db or not identifier:
            return None

        clean_id = identifier.strip()
        try:
            eq = None
            # 1. Intentar buscar por UUID
            try:
                eq_uuid = uuid.UUID(clean_id)
                query = select(Equipment).where(Equipment.id == eq_uuid, Equipment.is_active == True)
                result = await db.execute(query)
                eq = result.scalars().first()
            except ValueError:
                pass

            # 2. Si no es UUID, buscar por TAG exacto o case-insensitive
            if not eq:
                query = select(Equipment).where(
                    Equipment.tag_number.ilike(f"%{clean_id}%"),
                    Equipment.is_active == True
                )
                result = await db.execute(query)
                eq = result.scalars().first()

            # 3. Si no se encontró, probar con la tabla de alias canónicos
            if not eq:
                clean_upper = clean_id.upper()
                alias_tag = TAG_ALIASES.get(clean_upper)
                if alias_tag:
                    query = select(Equipment).where(
                        Equipment.tag_number.ilike(f"%{alias_tag}%"),
                        Equipment.is_active == True
                    )
                    result = await db.execute(query)
                    eq = result.scalars().first()

            if not eq:
                return None

            # 4. Obtener últimas 50 lecturas de métricas (necesarias para medias móviles de 12h en XGBoost)
            metric_q = (
                select(EquipmentMetricHistory)
                .where(EquipmentMetricHistory.equipment_id == eq.id)
                .order_by(desc(EquipmentMetricHistory.recorded_at))
                .limit(50)
            )
            metric_res = await db.execute(metric_q)
            metricas_recientes = metric_res.scalars().all()
            latest_metric = metricas_recientes[0] if metricas_recientes else None

            # 5. Obtener historial de fallas reales (últimas 5)
            failures_q = (
                select(FailureHistory)
                .where(FailureHistory.equipment_id == eq.id)
                .order_by(desc(FailureHistory.failure_date))
                .limit(5)
            )
            ultimas_fallas = (await db.execute(failures_q)).scalars().all()

            # 6. Obtener historial de mantenimientos ejecutados (últimos 5)
            maint_hist_q = (
                select(MaintenanceHistory)
                .where(MaintenanceHistory.equipment_id == eq.id)
                .order_by(desc(MaintenanceHistory.execution_date))
                .limit(5)
            )
            ultimos_mantenimientos = (await db.execute(maint_hist_q)).scalars().all()

            # 7. Evaluar el modelo predictivo de Machine Learning (XGBoost)
            resultado_ml = evaluar_metrica_actual_ml(
                equipment=eq,
                metricas_orm=metricas_recientes,
                ultimas_fallas=ultimas_fallas,
                ultimos_mantenimientos=ultimos_mantenimientos
            )

            # 8. Obtener Feedback Loop (Correcciones de auditores humanos e IA previa)
            correcciones_q = (
                select(AICorrection, AIRecommendation)
                .join(AIRecommendation, AICorrection.recommendation_id == AIRecommendation.id)
                .where(AIRecommendation.equipment_id == eq.id)
                .order_by(desc(AICorrection.created_at))
                .limit(3)
            )
            correcciones_rows = (await db.execute(correcciones_q)).all()

            # 9. Obtener estudios AMEF aprobados o recientes
            fmea_q = (
                select(FMEAAnalysis)
                .where(FMEAAnalysis.equipment_id == eq.id)
                .order_by(desc(FMEAAnalysis.created_at))
                .limit(3)
            )
            fmea_res = await db.execute(fmea_q)
            fmeas = fmea_res.scalars().all()

            # 10. Obtener criticidad completa
            crit_q = select(EquipmentCriticality).where(EquipmentCriticality.equipment_id == eq.id)
            crit_res = await db.execute(crit_q)
            crit = crit_res.scalars().first()

            specific_m = latest_metric.specific_metrics if latest_metric and latest_metric.specific_metrics else {"presion_descarga_psi": 850, "amperaje_motor": 142}
            tech_specs = eq.technical_specifications or {}
            rpm_val = self._extract_rpm(specific_m, tech_specs)
            is_failed = self._is_failed_status(eq.operational_status)

            base_crit = crit.criticality_level if crit else "Clase B (Semicrítico)"
            effective_crit = f"CRÍTICO - EN FALLA ({base_crit})" if is_failed else base_crit

            context = {
                "id": str(eq.id),
                "tag_number": eq.tag_number,
                "name": eq.name,
                "equipment_type": eq.equipment_type,
                "operational_status": eq.operational_status,
                "is_failed_status": is_failed,
                "velocidad_rpm": rpm_val,
                "usage_time": float(eq.usage_time) if getattr(eq, "usage_time", None) is not None else 1840.0,
                "brand": eq.brand or "Industrial Certificado",
                "model": eq.model or "API 610/618",
                "function_description": eq.function_description or "Operación continua de procesamiento y transporte de hidrocarburos.",
                "specs": tech_specs,
                "criticality": effective_crit,
                "rpn_score": crit.rpn_score if crit else 160,
                "criticality_breakdown": {
                    "safety": getattr(crit, "safety_impact_score", None),
                    "environmental": getattr(crit, "environmental_impact_score", None),
                    "operational": getattr(crit, "operational_impact_score", None),
                    "cost": getattr(crit, "maintenance_cost_score", None),
                } if crit else None,
                "ml_prediction": {
                    "probabilidad_falla": resultado_ml["probabilidad_falla"],
                    "probabilidad_falla_pct": round(resultado_ml["probabilidad_falla"] * 100, 2),
                    "clasificacion_alerta": resultado_ml["clasificacion_alerta"],
                    "salto_amperaje": resultado_ml["salto_amperaje"],
                    "dias_ultima_falla": resultado_ml["dias_ultima_falla"],
                    "dias_ultimo_mantenimiento": resultado_ml["dias_ultimo_mantenimiento"],
                },
                "latest_metric": {
                    "vibration_mm_s": float(latest_metric.vibration_mm_s) if latest_metric and latest_metric.vibration_mm_s is not None else 5.2,
                    "temperature_celsius": float(latest_metric.temperature_celsius) if latest_metric and latest_metric.temperature_celsius is not None else 78.5,
                    "operating_hours": float(latest_metric.operating_hours) if latest_metric and latest_metric.operating_hours is not None else 1840.0,
                    "velocidad_rpm": rpm_val,
                    "specific_metrics": specific_m,
                    "notes": latest_metric.notes if latest_metric else "Inspección rutinaria de sensores por condición.",
                    "recorded_at": latest_metric.recorded_at.isoformat() if latest_metric else datetime.now(timezone.utc).isoformat()
                },
                "recent_telemetry_trend": [
                    {
                        "recorded_at": m.recorded_at.isoformat() if m.recorded_at else "",
                        "temperature_celsius": float(m.temperature_celsius) if m.temperature_celsius is not None else 0.0,
                        "vibration_mm_s": float(m.vibration_mm_s) if m.vibration_mm_s is not None else 0.0,
                        "specific_metrics": m.specific_metrics or {}
                    }
                    for m in metricas_recientes[:6]
                ],
                "failure_history": [
                    {
                        "failure_date": f.failure_date.isoformat() if getattr(f, "failure_date", None) else "N/D",
                        "failure_mode": getattr(f, "failure_mode", "N/D"),
                        "severity": getattr(f, "severity", "N/D"),
                        "downtime_hours": float(getattr(f, "downtime_hours", 0.0) or 0.0),
                        "description": getattr(f, "description", "")
                    }
                    for f in ultimas_fallas
                ],
                "maintenance_history": [
                    {
                        "execution_date": m.execution_date.isoformat() if getattr(m, "execution_date", None) else "N/D",
                        "action_taken": getattr(m, "action_taken", "N/D"),
                        "replaced_parts": getattr(m, "replaced_parts", "Ninguno")
                    }
                    for m in ultimos_mantenimientos
                ],
                "human_corrections": [
                    {
                        "original_prediction": rec.prediction_type,
                        "corrected_text": corr.corrected_text
                    }
                    for corr, rec in correcciones_rows
                ],
                "fmeas": [
                    {
                        "title": f.title,
                        "severity": f.severity,
                        "frequency": f.frequency,
                        "detectability": f.detectability,
                        "recommended_actions": f.recommended_actions
                    }
                    for f in fmeas
                ]
            }
            return context

        except Exception as e:
            logger.error(f"[RCM CHATBOT] Error consultando contexto de equipo '{identifier}': {e}")
            return None

    def _extract_tag_from_text(self, text: str) -> Optional[str]:
        """Detecta menciones a TAGs reales de base de datos o nombres clave dentro del texto."""
        text_upper = text.upper()

        # 1. Tags directos de la BD PostgreSQL
        db_tags = [
            "K-201A", "K-201B", "K-301", "K-302",
            "P-501A", "P-601", "P-401A", "P-401B",
            "TK-101", "TK-102", "TK-103", "TK-104",
            "CMP-101A", "BOMBA-CENTRIFUGA-01"
        ]
        for dt in db_tags:
            if dt in text_upper:
                return dt

        # 2. Tags canónicos y alias comunes
        for alias, canon in TAG_ALIASES.items():
            if alias in text_upper:
                return canon

        # 3. Patrón genérico de TAG industrial (ej. P-101, K-500, TK-200)
        generic_tag_match = re.search(r"\b(TK|CMP|BOM|P|K)-\d{2,4}[A-Z]?\b", text_upper)
        if generic_tag_match:
            return generic_tag_match.group(0)

        # 4. Detección por palabras clave tecnológicas (solo si no es una consulta global de equipos)
        if not self._is_global_plant_query(text):
            if "BCP" in text_upper or "CAVIDAD PROGRESIVA" in text_upper:
                return "P-501A"
            if "BES" in text_upper or "ELECTROSUMERGIBLE" in text_upper:
                return "P-601"
            if "COMPRESOR" in text_upper or "RECIPROCANTE" in text_upper:
                return "K-201A"
            if "OLEODUCTO" in text_upper or "BOMBA MULTIETAPA" in text_upper:
                return "P-401A"
            if "SEPARADOR" in text_upper or "TRIFASICO" in text_upper or "SEDIMENTADOR" in text_upper:
                return "TK-103"
            if "TANQUE" in text_upper or "CRUDO" in text_upper:
                return "TK-101"
            if "GLP" in text_upper or "BALA" in text_upper:
                return "TK-104"
            if "BOMBA" in text_upper:
                return "BOMBA-CENTRIFUGA-01"

        return None

    async def _resolve_dynamic_tag_from_db(self, db: AsyncSession, text: str) -> Optional[str]:
        """Busca si el mensaje menciona el tag_number o nombre exacto de algún equipo registrado en BD."""
        if not db or not text:
            return None
        try:
            text_upper = text.upper()
            q = select(Equipment.tag_number, Equipment.name).where(
                Equipment.is_active == True,
                Equipment.deleted_at.is_(None)
            )
            rows = (await db.execute(q)).all()
            for tag_num, eq_name in rows:
                if tag_num and tag_num.upper() in text_upper:
                    return tag_num
                if eq_name and len(eq_name) > 5 and eq_name.upper() in text_upper:
                    return tag_num
        except Exception as e:
            logger.warning(f"[RCM CHATBOT] No se pudo resolver tag dinámico en BD: {e}")
        return None

    def _is_probability_query(self, message: str) -> bool:
        """Detecta si el usuario pregunta específicamente por probabilidad de falla, predicción ML (>=40%) o equipos por dañarse."""
        msg_low = message.lower()
        prob_keywords = [
            "probabilidad", "prediccion", "predicción", "40%", "modelo", "xgboost",
            "se dane", "se dañe", "danarse", "dañarse", "riesgo de falla",
            "propensos a fallar", "pueden fallar", "vayan a fallar", "falla inminente"
        ]
        return any(k in msg_low for k in prob_keywords)

    def _is_critical_equipment_query(self, message: str) -> bool:
        """Detecta si el usuario pide los equipos críticos, en estado failed/falla, Clase A o por RPN."""
        msg_low = message.lower()
        crit_keywords = [
            "equipos criticos", "equipos críticos", "maquinas criticas", "máquinas críticas",
            "activos criticos", "activos críticos", "listar criticos", "listar críticos",
            "cuales son los criticos", "cuáles son los críticos", "failed", "en falla",
            "equipos dañados", "equipos danados", "clase a", "mayor rpn", "ranking de criticidad"
        ]
        return any(k in msg_low for k in crit_keywords)

    def _is_global_plant_query(self, message: str) -> bool:
        """Determina si el usuario está consultando por todas las máquinas, equipos críticos o probabilidades de falla."""
        if self._is_probability_query(message) or self._is_critical_equipment_query(message):
            return True
        msg_low = message.lower()
        keywords = [
            "todas las maquinas", "todas las máquinas", "todos los equipos", "todos los activos",
            "estado de la planta", "riesgo global", "cuales estan en riesgo", "cuáles están en riesgo",
            "equipos en alerta", "lista de equipos", "lista de maquinas", "lista de máquinas",
            "matriz de criticidad", "resumen de planta", "inventario de maquinas", "inventario de equipos"
        ]
        return any(k in msg_low for k in keywords)

    async def create_work_order_from_chat(
        self,
        db: AsyncSession,
        title: str,
        equipment_id_or_tag: str,
        priority: str = "Alta",
        technician_notes: Optional[str] = None,
        scheduled_for: Optional[datetime] = None,
        current_user_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """Crea físicamente una Orden de Trabajo (WorkOrder) en PostgreSQL vinculada al activo."""
        eq_context = await self.get_equipment_db_context(db, equipment_id_or_tag)
        if not eq_context:
            return {
                "success": False,
                "error": f"No se encontró el activo '{equipment_id_or_tag}' en la base de datos."
            }

        eq_id = uuid.UUID(eq_context["id"])
        creator_id = await self.get_default_user_id(db, current_user_id)

        # Buscar o crear Maintenance Plan asociado
        maint_q = (
            select(Maintenance)
            .where(Maintenance.equipment_id == eq_id, Maintenance.is_active == True)
            .order_by(desc(Maintenance.created_at))
            .limit(1)
        )
        maint_res = await db.execute(maint_q)
        maint = maint_res.scalars().first()

        if not maint:
            maint_type = "Predictivo" if ("vibracion" in title.lower() or "temperatura" in title.lower()) else "Correctivo"
            maint = Maintenance(
                equipment_id=eq_id,
                title=f"Plan RCM {maint_type} - {eq_context['tag_number']}",
                maintenance_type=maint_type,
                description=f"Plan generado automáticamente por el Copiloto Heimdall RCM para el activo {eq_context['tag_number']} ({eq_context['name']}).",
                frequency_days=30,
                is_active=True,
                created_by=creator_id
            )
            db.add(maint)
            await db.commit()
            await db.refresh(maint)

        # Crear WorkOrder física
        priority_valid = priority if priority in ["Baja", "Normal", "Alta", "Urgente"] else "Alta"
        m = eq_context.get("latest_metric") or {}
        ml_info = eq_context.get("ml_prediction") or {}
        vib = m.get("vibration_mm_s")
        rpm = eq_context.get("velocidad_rpm", 0.0)
        prob_pct = ml_info.get("probabilidad_falla_pct", 0.0)
        notes = (
            technician_notes
            or f"Orden de trabajo generada automáticamente por el Copiloto Heimdall RCM. "
            f"Motivo: {title}. Estado actual: {eq_context.get('operational_status')}. "
            f"Severidad de vibración: {vib if vib is not None else 'N/D'} mm/s RMS | RPM: {rpm}. "
            f"Probabilidad de falla ML (XGBoost): {prob_pct}%."
        )

        wo = WorkOrder(
            maintenance_id=maint.id,
            status="Pendiente",
            priority=priority_valid,
            scheduled_for=scheduled_for or datetime.now(timezone.utc),
            technician_notes=notes,
            created_by=creator_id
        )
        db.add(wo)
        await db.commit()
        await db.refresh(wo)

        logger.info(f"[RCM CHATBOT] Orden de Trabajo {wo.id} creada en PostgreSQL para {eq_context['tag_number']}.")

        return {
            "success": True,
            "work_order_id": str(wo.id),
            "maintenance_id": str(maint.id),
            "equipment_id": str(eq_id),
            "equipment_tag": eq_context["tag_number"],
            "equipment_name": eq_context["name"],
            "title": title,
            "priority": wo.priority,
            "status": wo.status,
            "notes": notes,
            "created_at": wo.created_at.isoformat()
        }

    async def create_maintenance_plan_from_chat(
        self,
        db: AsyncSession,
        title: str,
        equipment_id_or_tag: str,
        maintenance_type: str = "Predictivo",
        frequency_days: int = 30,
        description: Optional[str] = None,
        current_user_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """Crea físicamente un Plan de Mantenimiento en PostgreSQL."""
        eq_context = await self.get_equipment_db_context(db, equipment_id_or_tag)
        if not eq_context:
            return {
                "success": False,
                "error": f"No se encontró el activo '{equipment_id_or_tag}' en la base de datos."
            }

        eq_id = uuid.UUID(eq_context["id"])
        creator_id = await self.get_default_user_id(db, current_user_id)

        valid_types = ["Preventivo", "Predictivo", "Correctivo", "Por Condición"]
        m_type = maintenance_type if maintenance_type in valid_types else "Predictivo"

        maint = Maintenance(
            equipment_id=eq_id,
            title=title,
            maintenance_type=m_type,
            description=description or f"Plan maestro de mantenimiento {m_type} generado por Copiloto IA para {eq_context['tag_number']} ({eq_context['name']}).",
            frequency_days=frequency_days or 30,
            is_active=True,
            created_by=creator_id
        )
        db.add(maint)
        await db.commit()
        await db.refresh(maint)

        logger.info(f"[RCM CHATBOT] Plan de Mantenimiento {maint.id} creado en PostgreSQL para {eq_context['tag_number']}.")

        return {
            "success": True,
            "maintenance_id": str(maint.id),
            "equipment_id": str(eq_id),
            "equipment_tag": eq_context["tag_number"],
            "equipment_name": eq_context["name"],
            "title": maint.title,
            "maintenance_type": maint.maintenance_type,
            "frequency_days": maint.frequency_days,
            "status": "Activo",
            "created_at": maint.created_at.isoformat()
        }

    async def process_message(
        self,
        message: str,
        session_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        mime_type: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        current_user_info: Optional[str] = None,
        current_user_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """
        Procesa la consulta técnica del usuario integrando historial, telemetría de BD,
        inferencia ML (XGBoost), escaneo global de planta, equipos con status == 'failed',
        ejecución conversacional de órdenes/planes y análisis multimodal.
        """
        session_id = session_id or self.generate_session_id()
        history = self.conversations.get(session_id, [])

        # 1. Resolver activo mencionado o seleccionado (estático + dinámico desde BD)
        target_tag = equipment_id or self._extract_tag_from_text(message)
        if not target_tag and db and not self._is_global_plant_query(message):
            target_tag = await self._resolve_dynamic_tag_from_db(db, message)

        eq_context = None
        if db and target_tag:
            eq_context = await self.get_equipment_db_context(db, target_tag)

        # 1.b Si el usuario pregunta por equipos críticos, probabilidades de falla o todas las máquinas
        plant_global_context = None
        if db and (not eq_context or self._is_global_plant_query(message)):
            plant_global_context = await self.get_plant_global_context(db)

        # 2. Detección de intenciones de CREACIÓN directa
        wo_match = re.search(
            r"(crea|crear|genera|generar|emite|emitir|abre|abrir|hacer|haz|expedir|expide)\s+(una\s+|la\s+)?(orden de trabajo|ot|ticket|orden)",
            message,
            re.IGNORECASE
        ) or re.search(r"\b(generar|crear)\s+ot\b", message, re.IGNORECASE)
        
        plan_match = re.search(
            r"(crea|crear|genera|generar|programa|programar)\s+(un\s+|el\s+)?(plan|rutina)\s+(de\s+)?(mantenimiento)?",
            message,
            re.IGNORECASE
        )

        action_executed = None
        action_proposal = None
        response_text = None

        # Si el usuario solicitó crear una Orden de Trabajo o Plan
        if db and (wo_match or plan_match):
            target_for_action = target_tag
            if not target_for_action:
                for msg in reversed(history):
                    hist_tag = self._extract_tag_from_text(msg.get("content", ""))
                    if hist_tag:
                        target_for_action = hist_tag
                        break

            if target_for_action:
                if wo_match:
                    prio = "Alta"
                    msg_low = message.lower()
                    if "urgente" in msg_low or "inmediata" in msg_low or "critica" in msg_low:
                        prio = "Urgente"
                    elif "baja" in msg_low:
                        prio = "Baja"
                    elif "normal" in msg_low or "media" in msg_low:
                        prio = "Normal"

                    title = f"Intervención Correctiva RCM - {target_for_action}"
                    if "vibracion" in msg_low:
                        title = f"Inspección por Vibración Anómala - {target_for_action}"
                    elif "temperatura" in msg_low:
                        title = f"Inspección por Sobrecalentamiento - {target_for_action}"
                    elif "fuga" in msg_low or "sello" in msg_low:
                        title = f"Reparación de Sello / Fuga - {target_for_action}"

                    res_wo = await self.create_work_order_from_chat(
                        db=db,
                        title=title,
                        equipment_id_or_tag=target_for_action,
                        priority=prio,
                        technician_notes=f"Generada directamente vía Copiloto Heimdall RCM. Instrucción: '{message}'",
                        current_user_id=current_user_id
                    )

                    if res_wo.get("success"):
                        action_executed = {
                            "type": "work_order_created",
                            "id": res_wo["work_order_id"],
                            "equipment_id": res_wo["equipment_id"],
                            "equipment_tag": res_wo["equipment_tag"],
                            "title": res_wo["title"],
                            "status": res_wo["status"],
                            "priority": res_wo["priority"],
                            "details": {
                                "maintenance_id": res_wo["maintenance_id"],
                                "notes": res_wo["notes"],
                                "created_at": res_wo["created_at"]
                            }
                        }
                        response_text = (
                            f"**Orden de Trabajo Registrada Exitosamente en PostgreSQL**\n\n"
                            f"- **ID / Folio**: `{res_wo['work_order_id']}`\n"
                            f"- **Activo**: `{res_wo['equipment_tag']}` ({res_wo['equipment_name']})\n"
                            f"- **Prioridad Operativa**: `{res_wo['priority']}`\n"
                            f"- **Estado Inicial**: `{res_wo['status']}`\n"
                            f"- **Plan Vinculado**: `{res_wo['maintenance_id']}`\n"
                            f"- **Fecha de Emisión**: `{res_wo['created_at']}`\n\n"
                            f"**Protocolo de Despacho Técnico (SAE JA1011)**:\n"
                            f"1. La orden ha sido asignada a la cola general para despacho de cuadrilla en campo.\n"
                            f"2. Procedimiento de Seguridad: Aplicar Bloqueo y Etiquetado (LOTO) previo a la intervención.\n"
                            f"3. Monitoreo Post-Mantenimiento: Registrar firma espectral de vibración tras el ajuste para validar la eliminación del modo de falla."
                        )

                elif plan_match:
                    m_type = "Predictivo"
                    msg_low = message.lower()
                    if "preventivo" in msg_low:
                        m_type = "Preventivo"
                    elif "correctivo" in msg_low:
                        m_type = "Correctivo"

                    title = f"Plan RCM {m_type} - {target_for_action}"
                    res_m = await self.create_maintenance_plan_from_chat(
                        db=db,
                        title=title,
                        equipment_id_or_tag=target_for_action,
                        maintenance_type=m_type,
                        frequency_days=30,
                        current_user_id=current_user_id
                    )
                    if res_m.get("success"):
                        action_executed = {
                            "type": "maintenance_plan_created",
                            "id": res_m["maintenance_id"],
                            "equipment_id": res_m["equipment_id"],
                            "equipment_tag": res_m["equipment_tag"],
                            "title": res_m["title"],
                            "status": "Activo",
                            "details": {
                                "maintenance_type": res_m["maintenance_type"],
                                "frequency_days": res_m["frequency_days"]
                            }
                        }
                        response_text = (
                            f"**Plan de Mantenimiento Registrado Exitosamente en PostgreSQL**\n\n"
                            f"- **ID de Plan**: `{res_m['maintenance_id']}`\n"
                            f"- **Activo**: `{res_m['equipment_tag']}` ({res_m['equipment_name']})\n"
                            f"- **Tipo de Mantenimiento**: `{res_m['maintenance_type']}`\n"
                            f"- **Frecuencia Programada**: Cada {res_m['frequency_days']} días\n"
                            f"- **Estado**: `Activo`\n\n"
                            f"**Estrategia RCM**:\n"
                            f"El plan se encuentra operativo en el cronograma de confiabilidad. "
                            f"A partir de este registro se programarán inspecciones periódicas y monitoreo por condición P-F."
                        )

        # 3. Si no fue una acción directa de creación, construir el prompt de IA o recurrir al dossier técnico
        if not response_text:
            # Construir Action Proposal interactivo si se detecta un activo
            if eq_context:
                m = eq_context.get("latest_metric") or {}
                ml_pred = eq_context.get("ml_prediction") or {}
                vib = m.get("vibration_mm_s")
                temp = m.get("temperature_celsius")
                crit_rpn = eq_context.get("rpn_score") or 0
                prob_ml = ml_pred.get("probabilidad_falla", 0.0)
                is_failed = eq_context.get("is_failed_status", False)

                prio = "Normal"
                if is_failed or (vib and vib > 7.1) or (temp and temp > 85) or (prob_ml >= 0.70):
                    prio = "Urgente"
                elif (vib and vib > 4.5) or (temp and temp > 70) or (crit_rpn >= 150) or (prob_ml >= 0.40):
                    prio = "Alta"

                action_proposal = {
                    "type": "create_work_order",
                    "equipment_id": str(eq_context["id"]),
                    "equipment_tag": eq_context["tag_number"],
                    "equipment_name": eq_context["name"],
                    "title": f"Inspección RCM {'Urgente' if prio == 'Urgente' else 'Preventiva'} - {eq_context['tag_number']}",
                    "priority": prio,
                    "description": (
                        f"Rutina de inspección y mitigación técnica para {eq_context['tag_number']} ({eq_context['name']}) "
                        f"por condición operativa (Status: {eq_context.get('operational_status')} | {vib or 'N/D'} mm/s RMS | "
                        f"RPM: {eq_context.get('velocidad_rpm', 0.0)} | Riesgo ML: {ml_pred.get('probabilidad_falla_pct', 0)}%)."
                    ),
                    "suggested_frequency_days": 15 if prio in ["Urgente", "Alta"] else 30
                }

            full_prompt = f"{self.system_prompt}\n\n"
            if current_user_info:
                full_prompt += f"USUARIO CONSULTANTE: {current_user_info}\n\n"

            # Inyectar el contexto específico del equipo con telemetría + RPM + status failed + ML + historial
            if eq_context:
                ml_p = eq_context.get("ml_prediction") or {}
                full_prompt += (
                    "--- TELEMETRÍA, PREDICCIÓN ML (XGBOOST) Y CONTEXTO EN VIVO DEL ACTIVO ---\n"
                    f"TAG: {eq_context['tag_number']} ({eq_context['name']})\n"
                    f"Tipo: {eq_context['equipment_type']} | Estado Operacional en BD: {eq_context['operational_status'].upper()} "
                    f"{'[CRÍTICO: EQUIPO EN ESTADO FAILED / FALLA]' if eq_context.get('is_failed_status') else ''}\n"
                    f"Fabricante / Modelo: {eq_context.get('brand')} / {eq_context.get('model')}\n"
                    f"Criticidad RCM: {eq_context['criticality']} (RPN: {eq_context['rpn_score']})\n"
                    f"Velocidad Nominal / Actual (RPM): {eq_context.get('velocidad_rpm')} RPM\n"
                    f"Función Primaria: {eq_context['function_description']}\n"
                    f"Especificaciones Técnicas: {eq_context.get('specs')}\n\n"
                    f"RESULTADO DEL MODELO PREDICTIVO DE MACHINE LEARNING (XGBOOST MULTI-EQUIPO):\n"
                    f"  - Probabilidad de Falla Inminente (<48h): {ml_p.get('probabilidad_falla_pct')}%\n"
                    f"  - Clasificación de Alerta ML: {ml_p.get('clasificacion_alerta')}\n"
                    f"  - Salto de Amperaje (Delta): {ml_p.get('salto_amperaje')} A\n"
                    f"  - Días desde última falla: {ml_p.get('dias_ultima_falla')} días\n"
                    f"  - Días desde último mantenimiento: {ml_p.get('dias_ultimo_mantenimiento')} días\n\n"
                )
                if eq_context.get("latest_metric"):
                    m = eq_context["latest_metric"]
                    full_prompt += (
                        f"Última Lectura de Sensores ({m.get('recorded_at', 'reciente')}):\n"
                        f"  - Vibración RMS: {m.get('vibration_mm_s')} mm/s\n"
                        f"  - Temperatura: {m.get('temperature_celsius')} °C\n"
                        f"  - Velocidad (RPM): {m.get('velocidad_rpm')} RPM\n"
                        f"  - Horas Operación: {m.get('operating_hours')} hrs\n"
                        f"  - Variables de Proceso: {m.get('specific_metrics')}\n"
                        f"  - Notas de Inspección: {m.get('notes')}\n\n"
                    )
                if eq_context.get("failure_history"):
                    full_prompt += "Historial Reciente de Fallas Reales:\n"
                    for fh in eq_context["failure_history"]:
                        full_prompt += f"  * {fh['failure_date']} | Modo: {fh['failure_mode']} | Severidad: {fh['severity']} | Parada: {fh['downtime_hours']}h | {fh['description']}\n"
                    full_prompt += "\n"
                if eq_context.get("maintenance_history"):
                    full_prompt += "Historial Reciente de Mantenimientos Ejecutados:\n"
                    for mh in eq_context["maintenance_history"]:
                        full_prompt += f"  * {mh['execution_date']} | Acción: {mh['action_taken']} | Repuestos: {mh['replaced_parts']}\n"
                    full_prompt += "\n"
                if eq_context.get("human_corrections"):
                    full_prompt += "Correcciones Previas de Auditores Humanos (Feedback Loop):\n"
                    for hc in eq_context["human_corrections"]:
                        full_prompt += f"  * Alerta previa '{hc['original_prediction']}' corregida por experto: '{hc['corrected_text']}'\n"
                    full_prompt += "\n"
                if eq_context.get("fmeas"):
                    full_prompt += "Modos de Falla Registrados (AMEF):\n"
                    for f in eq_context["fmeas"]:
                        full_prompt += f"  * {f['title']} (Severidad: {f.get('severity')}, Frecuencia: {f.get('frequency')})\n"
                full_prompt += "------------------------------------------------------------\n\n"

            # Inyectar también el radar global de planta (Equipos Críticos con status == failed / Clase A + Equipos con Probabilidad ML >= 40% y RPM)
            if plant_global_context:
                full_prompt += (
                    "--- PANORAMA GLOBAL DE PLANTA: EQUIPOS CRÍTICOS Y PROBABILIDAD DE FALLA (XGBOOST) ---\n"
                    f"Total de Equipos Activos Analizados: {plant_global_context['total_analizados']}\n"
                    f"Equipos con Estado Operativo 'failed' (En Falla Directa = Críticos): {plant_global_context['equipos_failed_count']}\n"
                    f"Total Equipos Críticos (Status 'failed' + Clase A / RPN >= 200 + Alerta ML Crítica): {plant_global_context['equipos_criticos_count']}\n"
                    f"Equipos con Probabilidad de Falla en Modelo ML (>= 40%): {plant_global_context['equipos_en_riesgo_ml_count']}\n"
                    f"Equipos en Operación Normal: {plant_global_context['equipos_sanos']}\n\n"
                    "1. LISTADO DE EQUIPOS CRÍTICOS (INCLUYE STATUS == 'failed' EN BD, CLASE A Y ALTO RPN):\n"
                )
                crit_list = plant_global_context.get("equipos_criticos_planta", [])
                if crit_list:
                    for item in crit_list:
                        full_prompt += (
                            f"  * TAG: {item['tag_number']} ({item['name']}) | "
                            f"Estado Operativo: {item['operational_status'].upper()} {'[CRÍTICO - FAILED]' if item['is_failed_status'] else ''} | "
                            f"Motivo Criticidad: {item['motivos_criticidad']} | "
                            f"RPN: {item['rpn_score']} | RPM: {item['velocidad_rpm']} RPM | "
                            f"Probabilidad Falla ML: {item['probabilidad_falla_pct']}% [{item['clasificacion_alerta_ml']}] | "
                            f"Vibración: {item['vibration_mm_s']} mm/s | Temp: {item['temperature_celsius']} °C\n"
                        )
                else:
                    full_prompt += "  * No se registran equipos en estado 'failed' ni en condición crítica actualmente.\n"

                full_prompt += "\n2. EQUIPOS CON PROBABILIDAD DE FALLA SEGÚN MODELO ML (XGBOOST >= 40% + RPM Y RPN):\n"
                prob_list = plant_global_context.get("equipos_probabilidad_ml", [])
                if prob_list:
                    for item in prob_list:
                        full_prompt += (
                            f"  * TAG: {item['tag_number']} ({item['name']}) | "
                            f"Probabilidad de Falla ML (<48h): {item['probabilidad_falla_pct']}% [{item['clasificacion_alerta_ml']}] | "
                            f"Velocidad: {item['velocidad_rpm']} RPM | RPN: {item['rpn_score']} | "
                            f"Estado BD: {item['operational_status']} | Salto Amperaje: {item['salto_amperaje']} A | "
                            f"Vibración: {item['vibration_mm_s']} mm/s | Temp: {item['temperature_celsius']} °C\n"
                        )
                else:
                    full_prompt += "  * Ningún equipo supera actualmente el 40% de probabilidad de falla en el modelo ML.\n"

                full_prompt += "\n3. INVENTARIO COMPLETO DE TODOS LOS EQUIPOS DE LA PLANTA:\n"
                for item in plant_global_context.get("inventario_planta", []):
                    full_prompt += (
                        f"  - TAG: {item['tag_number']} ({item['name']}) | Tipo: {item['equipment_type']} | "
                        f"Estado BD: {item['operational_status']} | Criticidad: {item['criticality_level']} (RPN: {item['rpn_score']}) | "
                        f"RPM: {item['velocidad_rpm']} | Probabilidad Falla ML (<48h): {item['probabilidad_falla_pct']}% [{item['clasificacion_alerta_ml']}] | "
                        f"Vibración: {item['vibration_mm_s']} mm/s | Temp: {item['temperature_celsius']} °C\n"
                    )
                full_prompt += "------------------------------------------------------------\n\n"

            if history:
                full_prompt += "HISTORIAL RECIENTE DE LA CONVERSACIÓN:\n"
                for msg in history[-8:]:
                    role_label = "Usuario" if msg.get("role") in ["user", "usuario"] else "Asesor"
                    full_prompt += f"{role_label}: {msg.get('content')}\n"
                full_prompt += "\n"

            full_prompt += f"Usuario: {message or '[Imagen adjunta sin texto]'}\n\nAsesor Heimdall RCM:"

            # Inferencia con Google GenAI
            if self.client:
                response_text = await self._generate_with_gemini(full_prompt, image_bytes, mime_type)

            # Motor determinista de contingencia si no hubo respuesta de la API externa
            if not response_text:
                logger.info("[RCM CHATBOT] Utilizando motor experto determinista de contingencia RCM.")
                response_text = self._fallback_rcm_engine(message, eq_context, plant_global_context)

        # 4. Actualizar memoria conversacional
        history.append({"role": "usuario", "content": message or "[Imagen adjunta]"})
        history.append({"role": "asesor", "content": response_text})
        if len(history) > 20:
            history = history[-20:]
        self.conversations[session_id] = history

        # 5. Extraer sugerencias técnicas y bloque RCM
        suggestions = self._extract_suggestions(response_text, eq_context)
        rcm_data = self._build_rcm_data(response_text, eq_context)

        return {
            "success": True,
            "response": response_text,
            "session_id": session_id,
            "suggestions": suggestions,
            "detected_equipment": eq_context,
            "plant_summary": plant_global_context if self._is_global_plant_query(message) else None,
            "rcm_data": rcm_data,
            "action_proposal": action_proposal,
            "action_executed": action_executed,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def _generate_with_gemini(
        self,
        full_prompt: str,
        image_bytes: Optional[bytes] = None,
        mime_type: Optional[str] = None
    ) -> Optional[str]:
        """Intenta invocar los modelos de Google GenAI con cascada automática ante errores 503."""
        contents = []

        if image_bytes and mime_type:
            try:
                img_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                contents.append(img_part)
                contents.append(types.Part.from_text(text=(
                    f"{full_prompt}\n\n[INSTRUCCIÓN VISUAL]: Analiza detalladamente la imagen adjunta. "
                    "Si es una placa de características técnicas, extrae TAG, RPM, potencia y especificaciones. "
                    "Si es un rodamiento, sello o válvula dañada, diagnostica el mecanismo de falla (cavitación, desgaste abrasivo, fatiga) "
                    "y su severidad bajo estándares RCM."
                )))
            except Exception as e:
                logger.error(f"[RCM CHATBOT] Error adjuntando imagen: {e}")
                contents = [full_prompt]
        else:
            contents = [full_prompt]

        config = types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=2048,
        )

        for model_name in CANDIDATE_MODELS:
            try:
                res = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                if res and res.text:
                    logger.info(f"[RCM CHATBOT] Respuesta generada exitosamente con modelo '{model_name}'.")
                    return res.text.strip()
            except Exception as e:
                logger.warning(f"[RCM CHATBOT] Modelo '{model_name}' no disponible ({e}). Probando siguiente...")
                continue

        return None

    def _format_equipment_deep_dossier(self, eq_context: Dict[str, Any]) -> str:
        """
        Genera un dossier técnico de ingeniería exhaustivo para el activo bajo normas
        ISO 14224, ISO 10816-3, SAE JA1011 y modelo predictivo XGBoost.
        """
        tag = eq_context['tag_number']
        name = eq_context['name']
        eq_type = eq_context.get('equipment_type', 'Rotativo')
        status = eq_context.get('operational_status', 'operational')
        is_failed = eq_context.get('is_failed_status', False)
        rpm = eq_context.get('velocidad_rpm', 0.0)
        brand = eq_context.get('brand') or 'Fabricante Industrial Certificado'
        model = eq_context.get('model') or 'Modelo Estándar API'
        func_desc = eq_context.get('function_description') or 'Transferencia y procesamiento continuo de fluidos en planta bajo especificaciones de caudal y presión.'
        specs = eq_context.get('specs') or {}
        criticality = eq_context.get('criticality', 'No evaluada')
        rpn = eq_context.get('rpn_score') or 'N/D'

        m = eq_context.get('latest_metric') or {}
        ml_pred = eq_context.get('ml_prediction') or {}
        vib = m.get('vibration_mm_s')
        temp = m.get('temperature_celsius')
        hours = m.get('operating_hours')
        rec_at = m.get('recorded_at') or 'Reciente'
        specifics = m.get('specific_metrics') or {}

        prob_pct = ml_pred.get('probabilidad_falla_pct', 0.0)
        alerta_ml = ml_pred.get('clasificacion_alerta', 'NORMAL')
        salto_amp = ml_pred.get('salto_amperaje', 0.0)
        dias_falla = ml_pred.get('dias_ultima_falla', 'N/D')
        dias_maint = ml_pred.get('dias_ultimo_mantenimiento', 'N/D')

        # Evaluación de vibración ISO 10816-3
        if vib is not None:
            if vib < 2.8:
                vib_zona = "Zona A (< 2.8 mm/s RMS)"
                vib_diagnostico = "Excelente estado mecánico. Máquina nueva o recién reacondicionada."
                nivel_alerta = "Bajo"
            elif vib <= 4.5:
                vib_zona = "Zona B (2.8 - 4.5 mm/s RMS)"
                vib_diagnostico = "Operación normal admisible sin restricciones de servicio continuo."
                nivel_alerta = "Normal"
            elif vib <= 7.1:
                vib_zona = "Zona C (4.5 - 7.1 mm/s RMS)"
                vib_diagnostico = "Alerta preventiva. Condición insatisfactoria para servicio continuo a largo plazo. Deterioro incipiente por desalineación, soltura mecánica o desgaste de rodamientos."
                nivel_alerta = "Alta"
            else:
                vib_zona = "Zona D (> 7.1 mm/s RMS)"
                vib_diagnostico = "Alarma crítica. Severidad vibratoria suficiente para causar daño inminente catastrófico. Se recomienda parada programada inmediata."
                nivel_alerta = "Urgente"
        else:
            vib_zona = "No disponible en PostgreSQL"
            vib_diagnostico = "Sin lecturas recientes de vibración registrada en el historial de sensores."
            nivel_alerta = "Normal"

        if is_failed or prob_pct >= 70.0:
            nivel_alerta = "Urgente"
        elif prob_pct >= 40.0 and nivel_alerta not in ["Urgente"]:
            nivel_alerta = "Alta"

        tag_upper = tag.upper()
        name_upper = name.upper()

        if "BCP" in tag_upper or "BCP" in name_upper or "P-501" in tag_upper:
            amef_tech = (
                "- **Modo de Falla 1**: Desgaste abrasivo del elastómero del estator (NBR/HNBR) por producción de sólidos/arena.\n"
                "  * *Causa Raíz*: Concentración de arena >200 ppm en fluido de fondo.\n"
                "  * *Efecto Funcional*: Pérdida de caudal de descarga y elevación de temperatura en cabeza de pozo.\n"
                "- **Modo de Falla 2**: Fatiga y corte de sarta de varillas de bombeo por torque oscilante.\n"
                "  * *Causa Raíz*: Operación fuera de la curva de torque nominal o bloqueo transitorio de rotor.\n"
                "  * *Efecto Funcional*: Parada no programada del pozo y caída inmediata de producción."
            )
            prescriptivo = (
                "1. Realizar monitoreo de amperaje del variador de frecuencia (VFD) y torque en cabezal cada 24 horas.\n"
                "2. Inspeccionar la presión de inyección química de desemulsionante y anti-fricción.\n"
                "3. Planificar prueba acústica de nivel dinámico de fluido (Echometer) para descartar sub-alimentación de bomba."
            )
        elif "CMP" in tag_upper or "COMPRESOR" in name_upper or "K-201" in tag_upper or "K-301" in tag_upper:
            amef_tech = (
                "- **Modo de Falla 1**: Fatiga cíclica y rotura de láminas en válvulas de succión/descarga Hoerbiger.\n"
                "  * *Causa Raíz*: Pulsación acústica resonante o arrastre intermitente de condensados líquidos.\n"
                "  * *Efecto Funcional*: Disminución del rendimiento volumétrico y elevación de temperatura en cilindros (>135 °C).\n"
                "- **Modo de Falla 2**: Desgaste de anillos de compresión (Rider rings) y cilindro.\n"
                "  * *Causa Raíz*: Lubricación deficiente o degradación de aceite sintético ISO VG 150.\n"
                "  * *Efecto Funcional*: Fuga entre etapas (blow-by) y sobrepresión en cárter."
            )
            prescriptivo = (
                "1. Inspección boroscópica semestral de los paquetes de válvulas sin desmontaje completo.\n"
                "2. Análisis espectral FFT de vibraciones con sensor acelerómetro piezoeléctrico en crucetas y cilindros.\n"
                "3. Verificación de temperatura diferencial entre succión y descarga (delta T < 45 °C por etapa)."
            )
        elif "BES" in tag_upper or "P-601" in tag_upper:
            amef_tech = (
                "- **Modo de Falla 1**: Degradación dieléctrica y cortocircuito en bobinado del motor sumergible.\n"
                "  * *Causa Raíz*: Infiltración de agua salada a través del sello del protector o temperatura de fondo >140 °C.\n"
                "  * *Efecto Funcional*: Disparo por sobrecorriente / falla a tierra en panel switchboard.\n"
                "- **Modo de Falla 2**: Colmatación por incrustaciones de carbonato de calcio (asfaltenos/scale) en el intake.\n"
                "  * *Causa Raíz*: Caída de presión por debajo de la presión de burbuja.\n"
                "  * *Efecto Funcional*: Cavitación en etapas superiores y reducción abrupta de flujo."
            )
            prescriptivo = (
                "1. Registro continuo de corriente trifásica y desbalance de fases (<2%).\n"
                "2. Monitoreo del sensor de fondo (temperatura de motor y presión de admisión intake).\n"
                "3. Inyección periódica de dispersante y secuestrante de scale en el anular."
            )
        else:
            amef_tech = (
                "- **Modo de Falla 1**: Desgaste abrasivo y picado en pistas de rodamiento por fatiga sub-superficial.\n"
                "  * *Causa Raíz*: Desalineación angular/paralela del acople o contaminación de lubricante con partículas sólidas.\n"
                "  * *Efecto Funcional*: Incremento de vibración en armónicos 1X y 2X, elevación térmica en cajetín.\n"
                "- **Modo de Falla 2**: Fuga catastrófica a través del sello mecánico (Plan API 53A).\n"
                "  * *Causa Raíz*: Desalineación del eje o sobrepresión transitoria en cámara de sello.\n"
                "  * *Efecto Funcional*: Fuga de fluido de proceso al ambiente, riesgo de seguridad ambiental."
            )
            prescriptivo = (
                "1. Ejecutar alineación láser en frío asegurando tolerancia angular < 0.05 mm y paralelismo < 0.03 mm.\n"
                "2. Re-engrase o reemplazo de lubricante con grasa sintética compleja de litio NLGI 2.\n"
                "3. Medición de espesores por ultrasonido en voluta y tuberías de succión/descarga."
            )

        status_label = f"`{status}` (**CRÍTICO - EQUIPO EN FALLA**)" if is_failed else f"`{status}`"

        return (
            f"### DOSSIER TÉCNICO DE INGENIERÍA: {tag} - {name}\n\n"
            f"#### 1. Ficha Técnica y Taxonomía del Activo (ISO 14224)\n"
            f"- **TAG Oficial**: `{tag}`\n"
            f"- **Clasificación**: `{eq_type}`\n"
            f"- **Fabricante / Modelo**: {brand} / {model}\n"
            f"- **Estado Operacional en BDD**: {status_label}\n"
            f"- **Función Primaria (SAE JA1011)**: {func_desc}\n"
            + (f"- **Especificaciones de Diseño**: `{specs}`\n" if specs else "") +
            f"\n#### 2. Telemetría de Sensores, Predicción ML (XGBoost) y Condición en Tiempo Real\n"
            f"- **Probabilidad de Falla Inminente (<48h - Modelo XGBoost)**: `{prob_pct}%` (**{alerta_ml}**)\n"
            f"- **Velocidad de Operación (RPM)**: `{rpm} RPM`\n"
            f"- **Salto Abrupto de Amperaje (Delta)**: `{salto_amp} A`\n"
            f"- **Severidad Vibratoria (ISO 10816-3)**: `{vib_zona}`\n"
            f"  * *Diagnóstico*: {vib_diagnostico}\n"
            f"- **Temperatura de Operación**: `{temp} °C`" + (" (Alerta térmica)" if temp and temp > 75 else " (Normal)") + "\n"
            f"- **Horas de Operación Acumuladas**: `{hours or 'N/D'} hrs`\n"
            f"- **Último Registro de Sensores**: `{rec_at}`\n"
            + (f"- **Variables de Proceso**: `{specifics}`\n" if specifics else "") +
            f"\n#### 3. Jerarquía de Criticidad, Historial y Matriz de Riesgo\n"
            f"- **Nivel de Criticidad**: **{criticality}**\n"
            f"- **Número de Prioridad de Riesgo (RPN / NPR)**: `{rpn}`\n"
            f"- **Tiempo desde Última Falla**: `{dias_falla} días` | **Tiempo desde Último Mantenimiento**: `{dias_maint} días`\n"
            f"- **Nivel de Alerta Integrado**: **{nivel_alerta}**\n\n"
            f"#### 4. Análisis AMEF de Modos de Falla Dominantes (SAE JA1011)\n"
            f"{amef_tech}\n\n"
            f"#### 5. Estrategia y Acciones Prescriptivas de Mantenimiento RCM\n"
            f"{prescriptivo}\n\n"
            f"#### 6. Propuesta de Acción Inmediata\n"
            f"Para este activo se recomienda emitir una **Orden de Trabajo con Prioridad {nivel_alerta}** "
            f"para verificación en campo de las holguras mecánicas y monitoreo espectral. "
            f"Puede generarla directamente pulsando el botón inferior o solicitando: *'Crea una orden de trabajo para {tag}'*."
        )

    def _fallback_rcm_engine(
        self,
        message: str,
        eq_context: Optional[Dict[str, Any]],
        plant_global_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Motor experto determinista de alta precisión basado en SAE JA1011, ISO 14224, ISO 10816 y XGBoost.
        Garantiza respuesta inmediata y exhaustiva si la API externa experimenta latencia.
        """
        clean = message.lower()

        # Si se identificó un activo específico en el contexto, emitir el dossier técnico completo con ML y RPM
        if eq_context and not self._is_global_plant_query(message):
            return self._format_equipment_deep_dossier(eq_context)

        # Si pregunta por equipos con probabilidad de falla (>=40% ML + RPM) o equipos críticos (status == 'failed' / Clase A)
        if plant_global_context and (self._is_global_plant_query(message) or not eq_context):
            crit_planta = plant_global_context.get("equipos_criticos_planta", [])
            prob_ml_list = plant_global_context.get("equipos_probabilidad_ml", [])

            bloque_criticos = ""
            if crit_planta:
                for item in crit_planta:
                    estado_str = f"`{item['operational_status'].upper()}` (**CRÍTICO - EN FALLA**)" if item["is_failed_status"] else f"`{item['operational_status']}`"
                    bloque_criticos += (
                        f"- **`{item['tag_number']}` ({item['name']})**: "
                        f"Estado: {estado_str} | "
                        f"Criticidad: **{item['criticality_level']}** (RPN: `{item['rpn_score']}`) | "
                        f"RPM: `{item['velocidad_rpm']} RPM` | "
                        f"Probabilidad Falla ML: `{item['probabilidad_falla_pct']}%` (`{item['clasificacion_alerta_ml']}`)\n"
                    )
            else:
                bloque_criticos = "- No se registran equipos en estado `failed` ni en condición crítica Clase A.\n"

            bloque_probabilidad = ""
            if prob_ml_list:
                for item in prob_ml_list:
                    bloque_probabilidad += (
                        f"- **`{item['tag_number']}` ({item['name']})**: "
                        f"Probabilidad de Falla ML (<48h): **`{item['probabilidad_falla_pct']}%`** (`{item['clasificacion_alerta_ml']}`) | "
                        f"Velocidad: **`{item['velocidad_rpm']} RPM`** | RPN: `{item['rpn_score']}` | "
                        f"Vib: `{item['vibration_mm_s']} mm/s` | Temp: `{item['temperature_celsius']} °C` | "
                        f"Estado BD: `{item['operational_status']}`\n"
                    )
            else:
                bloque_probabilidad = "- Ningún equipo supera actualmente el umbral del 40% de probabilidad de falla en el modelo ML.\n"

            # Si preguntó específicamente por probabilidad de falla, poner primero la sección de probabilidad (>=40% + RPM)
            if self._is_probability_query(message) and not self._is_critical_equipment_query(message):
                return (
                    "### EQUIPOS CON PROBABILIDAD DE FALLA (MODELO ML XGBOOST >= 40%)\n\n"
                    f"- **Total de Máquinas Evaluadas**: `{plant_global_context['total_analizados']}`\n"
                    f"- **Máquinas con Probabilidad de Falla (>= 40%)**: `{plant_global_context['equipos_en_riesgo_ml_count']}`\n"
                    f"- **Máquinas en Estado 'failed' (En Falla)**: `{plant_global_context['equipos_failed_count']}`\n\n"
                    "#### 1. Ranking de Equipos con Probabilidad de Falla Inminente (>= 40% ML + RPM)\n"
                    f"{bloque_probabilidad}\n"
                    "#### 2. Equipos Críticos por Estado Operativo (`failed`) o Matriz RCM (Clase A / RPN)\n"
                    f"{bloque_criticos}\n"
                    "Para generar una Orden de Trabajo o ver el dossier completo de un activo, indique su TAG (ejemplo: *'Crea una orden de trabajo para K-201A'*)."
                )

            return (
                "### LISTADO DE EQUIPOS CRÍTICOS Y RADAR PREDICTIVO DE PLANTA\n\n"
                f"- **Total de Máquinas Activas**: `{plant_global_context['total_analizados']}`\n"
                f"- **Equipos en Estado `failed` (Críticos en Falla Operativa)**: `{plant_global_context['equipos_failed_count']}`\n"
                f"- **Total Equipos Críticos (`failed` + Clase A / Alto RPN)**: `{plant_global_context['equipos_criticos_count']}`\n"
                f"- **Equipos con Probabilidad de Falla ML (>= 40%)**: `{plant_global_context['equipos_en_riesgo_ml_count']}`\n\n"
                "#### 1. Equipos Críticos (Estado `failed` en BD, Clase A y Alto RPN)\n"
                f"{bloque_criticos}\n"
                "#### 2. Equipos con Probabilidad de Falla en Modelo Predictivo (XGBoost >= 40% + RPM)\n"
                f"{bloque_probabilidad}\n"
                "Para abrir el dossier de ingeniería o crear una Orden de Trabajo sobre cualquier equipo crítico, indique su TAG (ejemplo: *'Crea una orden de trabajo urgente para K-201A'*)."
            )

        # Caso 1: Definición de RCM y las 7 preguntas
        if any(k in clean for k in ["que es rcm", "significa rcm", "metodologia rcm", "ja1011", "7 preguntas"]):
            return (
                "**Mantenimiento Centrado en Confiabilidad (RCM - SAE JA1011)**\n\n"
                "El RCM es un proceso sistemático utilizado para determinar qué debe hacerse para asegurar que cualquier "
                "activo físico continúe desempeñando las funciones deseadas en su contexto operacional actual.\n\n"
                "Para cumplir rigurosamente con la norma **SAE JA1011**, el estudio debe responder secuencialmente a las **7 Preguntas Fundamentales**:\n\n"
                "1. **¿Cuáles son las funciones y los estándares de desempeño asociados?** (Funciones primarias y secundarias).\n"
                "2. **¿De qué manera falla en cumplir sus funciones?** (Fallas funcionales totales o parciales).\n"
                "3. **¿Cuál es la causa de cada falla?** (Modos de falla a nivel de componente causa-raíz).\n"
                "4. **¿Qué ocurre cuando ocurre cada falla?** (Efectos de falla: alarmas, daños colaterales, pérdida de caudal).\n"
                "5. **¿De qué manera afecta cada falla?** (Consecuencias de falla: Seguridad, Medio Ambiente, Operacional o No Operacional).\n"
                "6. **¿Qué puede hacerse para prevenir o predecir la falla?** (Tareas proactivas: monitoreo por condición P-F, mantenimiento preventivo o reacondicionamiento cíclico).\n"
                "7. **¿Qué debe hacerse si no puede encontrarse una tarea proactiva adecuada?** (Acciones 'a falta de': rediseño de ingeniería, búsqueda de fallas ocultas o mantenimiento correctivo planificado)."
            )

        # Caso 2: Cálculo de Criticidad y Matriz de Riesgo
        if any(k in clean for k in ["criticidad", "matriz de riesgo", "calcular criticidad", "formula de criticidad"]):
            return (
                "**Metodología de Evaluación de Criticidad de Activos (Matriz de Riesgo RCM)**\n\n"
                "La criticidad jerarquiza los equipos para priorizar recursos de mantenimiento según su impacto operacional:\n\n"
                "$$\\text{Criticidad Total (CR)} = \\text{Frecuencia de Falla} \\times \\text{Consecuencia Total}$$\n\n"
                "Donde la **Consecuencia Total** se pondera según cuatro dimensiones:\n"
                "- **Impacto en Seguridad y Personas (S)** (Ponderación 1 a 10).\n"
                "- **Impacto Ambiental (E)** (Ponderación 1 a 10: derrames de nafta, venteo de H2S).\n"
                "- **Impacto Operacional / Producción Diferida (O)** (Ponderación 1 a 10: barriles netos diferidos).\n"
                "- **Costo de Reparación y Repuestos (C)** (Ponderación 1 a 10).\n\n"
                "**Categorías de Clasificación en Heimdall RCM**:\n"
                "- **Estado `failed` en Base de Datos**: Prioridad Crítica Inmediata (activo en falla).\n"
                "- **Clase A - Crítico (CR > 500 o RPN >= 200)**: Monitoreo predictivo continuo en línea y planes AMEF aprobados.\n"
                "- **Clase B - Semicrítico (CR entre 200 y 500)**: Inspección por condición quincenal y mantenimiento preventivo cíclico.\n"
                "- **Clase C - No Crítico (CR < 200)**: Mantenimiento correctivo planificado a falla permitida."
            )

        # Caso 3: Severidad de vibraciones ISO 10816
        if any(k in clean for k in ["iso 10816", "vibracion", "severidad vibratoria"]):
            return (
                "**Evaluación de Vibraciones Mecánicas en Maquinaria Industrial (Norma ISO 10816-3)**\n\n"
                "La norma ISO 10816-3 evalúa la velocidad cuadrática media (RMS en mm/s) medida sobre soportes y pedestales de rodamientos:\n\n"
                "- **Zona A (< 2.8 mm/s)**: Maquinaria nueva o recién reacondicionada en condiciones óptimas.\n"
                "- **Zona B (2.8 - 4.5 mm/s)**: Máquinas que operan normalmente sin restricciones temporales de servicio.\n"
                "- **Zona C (4.5 - 7.1 mm/s)**: Condición no satisfactoria para operación a largo plazo. Indica deterioro incipiente por desalineación, soltura mecánica o desgaste de rodamientos.\n"
                "- **Zona D (> 7.1 mm/s)**: Daño inminente. Se recomienda la parada planificada inmediata del activo para evitar fallas catastróficas.\n\n"
                "**Nota de Confiabilidad**: Siempre correlacione la vibración con las RPM, la temperatura del cajetín de rodamientos y el análisis tribológico de aceite lubricante."
            )

        # Caso genérico
        return (
            f"**Asistente Técnico Heimdall RCM**\n\n"
            f"Para su consulta sobre *'{message}'*:\n\n"
            "El sistema de confiabilidad industrial recomienda estructurar el análisis bajo los principios de **SAE JA1011**, **ISO 14224** y el motor predictivo **XGBoost**:\n"
            "1. **Equipos Críticos**: Pregunte *'Listar todos los equipos críticos'* para ver las máquinas con estado `failed`, Clase A y alto RPN.\n"
            "2. **Probabilidad de Falla**: Pregunte *'¿Qué equipos tienen probabilidad de falla?'* para ver los activos con riesgo >= 40% en el modelo ML junto con sus RPM y telemetría.\n"
            "3. **Emisión de Órdenes de Trabajo**: Puede solicitarme directamente: *'Crea una orden de trabajo para K-201A por vibración alta'* o *'Crear plan de mantenimiento predictivo'*."
        )

    def _extract_suggestions(self, text: str, eq_context: Optional[Dict[str, Any]]) -> List[str]:
        """Genera sugerencias de navegación y preguntas técnicas coherentes."""
        suggestions = []
        if eq_context:
            tag = eq_context['tag_number']
            suggestions.append(f"¿Cuál es la probabilidad de falla de {tag}?")
            suggestions.append(f"Crear orden de trabajo para {tag}")
            suggestions.append(f"Listar todos los equipos críticos")
            suggestions.append(f"Equipos con probabilidad de falla")
        else:
            suggestions.append("Listar todos los equipos críticos")
            suggestions.append("Equipos con probabilidad de falla")
            suggestions.append("Evaluar el estado del compresor K-201A")
            suggestions.append("¿Cuáles son las 7 preguntas de SAE JA1011?")

        return suggestions[:4]

    def _build_rcm_data(self, text: str, eq_context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Construye un bloque estructurado RCM + ML + RPM + Status para renderizado en componentes de UI."""
        if eq_context:
            tag = eq_context['tag_number']
            m = eq_context.get('latest_metric') or {}
            ml_pred = eq_context.get('ml_prediction') or {}
            vib = m.get('vibration_mm_s')
            prob_ml = ml_pred.get('probabilidad_falla', 0.0)
            is_failed = eq_context.get('is_failed_status', False)

            severity = "low"
            if is_failed or (vib and vib > 7.1) or prob_ml >= 0.70:
                severity = "critical"
            elif (vib and vib > 4.5) or prob_ml >= 0.40:
                severity = "high"

            return {
                "equipmentTag": tag,
                "equipmentName": eq_context['name'],
                "operationalStatus": eq_context.get('operational_status'),
                "isFailed": is_failed,
                "criticalityLevel": eq_context['criticality'],
                "rpnScore": eq_context.get('rpn_score'),
                "rpm": eq_context.get('velocidad_rpm', 0.0),
                "vibration_rms": vib,
                "temperature_c": m.get('temperature_celsius'),
                "failure_probability_pct": ml_pred.get('probabilidad_falla_pct', 0.0),
                "ml_alert_level": ml_pred.get('clasificacion_alerta', 'NORMAL'),
                "severity": severity,
                "recommendedTask": "Intervención correctiva inmediata (Equipo en estado FAILED)." if is_failed else (
                    "Inspección predictiva y verificación de alineación láser." if severity != "low" else "Monitoreo rutinario por condición."
                )
            }
        return None

    def clear_history(self, session_id: str) -> bool:
        if session_id in self.conversations:
            del self.conversations[session_id]
            return True
        return False

    def get_history(self, session_id: str) -> List[dict]:
        return self.conversations.get(session_id, [])

    def generate_session_id(self) -> str:
        return f"session_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:8]}"


# Instancia Singleton del servicio para toda la aplicación
rcm_chatbot_service = RcmChatbotService()