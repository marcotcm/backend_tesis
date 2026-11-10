"""
services/rcm_chatbot_service.py
Servicio Central del Asistente Conversacional RCM (Chatbot) con Inteligencia Artificial.
Inspirado en la arquitectura modular de maxton_ai_back (BeautyAdvisorService / Controller)
y adaptado al dominio de Mantenimiento Centrado en Confiabilidad (SAE JA1011, ISO 14224 e ISO 10816-3).
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

logger = logging.getLogger("rcm_chatbot")

# Modelos candidatos en orden de prioridad
CANDIDATE_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-2.5-pro",
]

class RcmChatbotService:
    """
    Servicio de Asesoría Técnica RCM y Diagnóstico Predictivo Inteligente.
    Gestiona el contexto conversacional, análisis multimodal (imágenes de componentes/placas)
    e inyección de telemetría de activos en tiempo real desde la base de datos PostgreSQL.
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
            "Severidad de Vibraciones Mecánicas (ISO 10816-3) y Gestión de Activos Industriales.\n\n"
            "TUS FUNCIONES PRINCIPALES:\n"
            "1. Responder dudas metodológicas sobre RCM y las 7 preguntas básicas de la norma SAE JA1011.\n"
            "2. Explicar el análisis de modos y efectos de falla (AMEF / FMEA) y el cálculo del Número de Prioridad de Riesgo (NPR = S x O x D).\n"
            "3. Evaluar la severidad de vibraciones bajo ISO 10816-3:\n"
            "   - Zona A (<2.8 mm/s RMS): Condición excelente de maquinaria nueva o reparada.\n"
            "   - Zona B (2.8 - 4.5 mm/s RMS): Operación normal sin restricciones.\n"
            "   - Zona C (4.5 - 7.1 mm/s RMS): Alerta preventiva, deterioro incipiente, planificar intervención.\n"
            "   - Zona D (>7.1 mm/s RMS): Daño inminente, parada recomendada de inmediato.\n"
            "4. Diagnosticar activos petroleros clave:\n"
            "   - Bombas de Cavidad Progresiva (BCP): desgaste de estator NBR/HNBR, fricción por arena, sobrecarga de motor.\n"
            "   - Compresores Reciprocantes: fatiga de válvulas de descarga, pulsación, arrastre de líquidos.\n"
            "   - Bombas Centrífugas: cavitación (NPSH), desalineación angular, falla de sellos mecánicos API 53A.\n"
            "   - Bombas Electrosumergibles (BES): degradación de aislamiento en fondo de pozo, temperatura de bobinado.\n"
            "   - Separadores Trifásicos: arrastre de emulsión, colmatación de coalescentes, control de interfase.\n"
            "   - Motogeneradores a Gas: variación de poder calorífico, detonación, luz de válvulas.\n"
            "5. Orientar en la apertura, diagnóstico y cierre técnico de Órdenes de Trabajo (OT).\n\n"
            "DIRECTRICES DE COMUNICACIÓN:\n"
            "- Responde en español técnico, claro, conciso y profesional.\n"
            "- NO utilices emojis en telemetría técnica, diagnósticos ni reportes de alarma industrial.\n"
            "- Cuando se consulte por un equipo específico, utiliza los datos reales de telemetría y AMEF provistos en el contexto.\n"
            "- Proporciona recomendaciones prescriptivas concretas (re-engrase con grasa sintética NLGI 2, alineación láser en frío, boroscopia, lapeado de válvulas).\n"
            "- Si el usuario envía una imagen, analiza si corresponde a una chapa técnica (extrae TAG, RPM, potencia), a una pieza con falla física (describe el mecanismo de desgaste) o a un gráfico de vibración."
        )

    async def get_equipment_db_context(self, db: AsyncSession, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Recupera información técnica, últimas métricas de sensores y AMEFs
        asociados a un TAG o UUID de equipo.
        """
        if not db or not identifier:
            return None

        try:
            eq = None
            # 1. Intentar buscar por UUID
            try:
                eq_uuid = uuid.UUID(identifier)
                query = select(Equipment).where(Equipment.id == eq_uuid, Equipment.is_active == True)
                result = await db.execute(query)
                eq = result.scalars().first()
            except ValueError:
                pass

            # 2. Si no es UUID, buscar por TAG exacto o case-insensitive
            if not eq:
                query = select(Equipment).where(
                    Equipment.tag_number.ilike(f"%{identifier.strip()}%"),
                    Equipment.is_active == True
                )
                result = await db.execute(query)
                eq = result.scalars().first()

            if not eq:
                return None

            # 3. Obtener última lectura de métricas
            metric_q = (
                select(EquipmentMetricHistory)
                .where(EquipmentMetricHistory.equipment_id == eq.id)
                .order_by(desc(EquipmentMetricHistory.recorded_at))
                .limit(1)
            )
            metric_res = await db.execute(metric_q)
            latest_metric = metric_res.scalars().first()

            # 4. Obtener estudios AMEF aprobados o recientes
            fmea_q = (
                select(FMEAAnalysis)
                .where(FMEAAnalysis.equipment_id == eq.id)
                .order_by(desc(FMEAAnalysis.rpn_score))
                .limit(3)
            )
            fmea_res = await db.execute(fmea_q)
            fmeas = fmea_res.scalars().all()

            # 5. Obtener criticidad
            crit_q = select(EquipmentCriticality).where(EquipmentCriticality.equipment_id == eq.id)
            crit_res = await db.execute(crit_q)
            crit = crit_res.scalars().first()

            context = {
                "id": str(eq.id),
                "tag_number": eq.tag_number,
                "name": eq.name,
                "equipment_type": eq.equipment_type,
                "operational_status": eq.operational_status,
                "brand": eq.brand,
                "model": eq.model,
                "function_description": eq.function_description,
                "specs": eq.technical_specifications or {},
                "criticality": crit.criticality_level if crit else "No evaluada",
                "rpn_score": crit.rpn_score if crit else None,
                "latest_metric": {
                    "vibration_mm_s": float(latest_metric.vibration_mm_s) if latest_metric and latest_metric.vibration_mm_s is not None else None,
                    "temperature_celsius": float(latest_metric.temperature_celsius) if latest_metric and latest_metric.temperature_celsius is not None else None,
                    "operating_hours": float(latest_metric.operating_hours) if latest_metric and latest_metric.operating_hours is not None else None,
                    "specific_metrics": latest_metric.specific_metrics if latest_metric else {},
                    "notes": latest_metric.notes if latest_metric else None,
                    "recorded_at": latest_metric.recorded_at.isoformat() if latest_metric else None
                } if latest_metric else None,
                "fmeas": [
                    {
                        "title": f.title,
                        "rpn": f.rpn_score,
                        "severity": f.severity,
                        "occurrence": f.occurrence,
                        "detection": f.detection,
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
        """Detecta menciones a TAGs conocidos de la planta dentro del texto del usuario."""
        known_tags = [
            "POZO-BCP-204", "BCP-204", "BCP 204", "POZO 204",
            "CMP-001", "CMP 001", "COMPRESOR-001",
            "BOM-DCO-102", "DCO-102", "BOMBA-102",
            "POZO-BES-512", "BES-512", "BES 512", "POZO 512",
            "SEP-TRI-301", "TRI-301", "SEPARADOR-301",
            "GEN-CAT-401", "CAT-401", "GENERADOR-401",
            "BOM-AGU-205", "AGU-205",
            "TUR-EXP-101", "EXP-101"
        ]
        text_upper = text.upper()
        for tag in known_tags:
            if tag in text_upper:
                # Normalizar a tag canónico
                if "204" in tag: return "POZO-BCP-204"
                if "001" in tag: return "CMP-001"
                if "102" in tag: return "BOM-DCO-102"
                if "512" in tag: return "POZO-BES-512"
                if "301" in tag: return "SEP-TRI-301"
                if "401" in tag: return "GEN-CAT-401"
                if "205" in tag: return "BOM-AGU-205"
                if "101" in tag: return "TUR-EXP-101"
        return None

    async def process_message(
        self,
        message: str,
        session_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        mime_type: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        current_user_info: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Procesa la consulta técnica del usuario integrando historial, telemetría de BD
        y análisis visual en caso de que se adjunte una imagen.
        """
        session_id = session_id or self.generate_session_id()
        history = self.conversations.get(session_id, [])

        # 1. Resolver si hay un equipo mencionado o seleccionado
        target_tag = equipment_id or self._extract_tag_from_text(message)
        eq_context = None
        if db and target_tag:
            eq_context = await self.get_equipment_db_context(db, target_tag)

        # 2. Construir el prompt enriquecido
        full_prompt = f"{self.system_prompt}\n\n"

        if current_user_info:
            full_prompt += f"USUARIO CONSULTANTE: {current_user_info}\n\n"

        if eq_context:
            full_prompt += (
                "--- TELEMETRÍA Y CONTEXTO EN VIVO DEL ACTIVO (BASE DE DATOS HEIMDALL) ---\n"
                f"TAG: {eq_context['tag_number']} ({eq_context['name']})\n"
                f"Tipo: {eq_context['equipment_type']} | Estado Operacional: {eq_context['operational_status']}\n"
                f"Criticidad: {eq_context['criticality']} (RPN: {eq_context['rpn_score']})\n"
                f"Función Primaria: {eq_context['function_description']}\n"
            )
            if eq_context.get("latest_metric"):
                m = eq_context["latest_metric"]
                full_prompt += (
                    f"Última Lectura de Sensores ({m.get('recorded_at', 'reciente')}):\n"
                    f"  - Vibración RMS: {m.get('vibration_mm_s')} mm/s\n"
                    f"  - Temperatura: {m.get('temperature_celsius')} °C\n"
                    f"  - Horas Operación: {m.get('operating_hours')} hrs\n"
                    f"  - Variables de Proceso: {m.get('specific_metrics')}\n"
                    f"  - Notas de Inspección: {m.get('notes')}\n"
                )
            if eq_context.get("fmeas"):
                full_prompt += "Modos de Falla Críticos Registrados (AMEF):\n"
                for f in eq_context["fmeas"]:
                    full_prompt += f"  * {f['title']} (RPN: {f['rpn']})\n"
            full_prompt += "------------------------------------------------------------\n\n"

        # 3. Incorporar historial reciente (últimos 8 turnos)
        if history:
            full_prompt += "HISTORIAL RECIENTE DE LA CONVERSACIÓN:\n"
            recent = history[-8:]
            for msg in recent:
                role_label = "Usuario" if msg.get("role") in ["user", "usuario"] else "Asesor"
                full_prompt += f"{role_label}: {msg.get('content')}\n"
            full_prompt += "\n"

        full_prompt += f"Usuario: {message or '[Imagen adjunta sin texto]'}\n\nAsesor Heimdall RCM:"

        # 4. Intentar inferencia con el cliente de Google GenAI
        response_text = None
        if self.client:
            response_text = await self._generate_with_gemini(full_prompt, image_bytes, mime_type)

        # 5. Si la API de Google no respondió (ej. cuota o demanda), recurrir al motor determinista de contingencia
        if not response_text:
            logger.info("[RCM CHATBOT] Utilizando motor experto determinista de contingencia RCM.")
            response_text = self._fallback_rcm_engine(message, eq_context)

        # 6. Actualizar historial de sesión en memoria
        history.append({"role": "usuario", "content": message or "[Imagen adjunta]"})
        history.append({"role": "asesor", "content": response_text})
        if len(history) > 20:
            history = history[-20:]
        self.conversations[session_id] = history

        # 7. Extraer sugerencias técnicas y datos RCM
        suggestions = self._extract_suggestions(response_text, eq_context)
        rcm_data = self._build_rcm_data(response_text, eq_context)

        return {
            "success": True,
            "response": response_text,
            "session_id": session_id,
            "suggestions": suggestions,
            "detected_equipment": eq_context,
            "rcm_data": rcm_data,
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
                # Invocación asíncrona mediante client.aio
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

    def _fallback_rcm_engine(self, message: str, eq_context: Optional[Dict[str, Any]]) -> str:
        """
        Motor experto determinista de alta precisión basado en SAE JA1011, ISO 14224 e ISO 10816.
        Garantiza respuesta inmediata si la API externa experimenta latencia o sobrecarga temporal.
        """
        clean = message.lower()

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
                "- **Clase A - Crítico (CR > 500)**: Monitoreo predictivo continuo en línea y planes AMEF aprobados.\n"
                "- **Clase B - Semicrítico (CR entre 200 y 500)**: Inspección por condición quincenal y mantenimiento preventivo cíclico.\n"
                "- **Clase C - No Crítico (CR < 200)**: Mantenimiento correctivo planificado a falla permitida."
            )

        # Caso 3: Evaluación de activo específico detectado en base de datos
        if eq_context:
            tag = eq_context['tag_number']
            name = eq_context['name']
            status = eq_context['operational_status']
            m = eq_context.get('latest_metric') or {}
            vib = m.get('vibration_mm_s')
            temp = m.get('temperature_celsius')

            vib_eval = "No disponible"
            zona = "N/D"
            if vib is not None:
                if vib < 2.8:
                    vib_eval = f"{vib} mm/s RMS (Zona A ISO 10816 - Excelente)"
                    zona = "Zona A"
                elif vib <= 4.5:
                    vib_eval = f"{vib} mm/s RMS (Zona B ISO 10816 - Buena/Aceptable)"
                    zona = "Zona B"
                elif vib <= 7.1:
                    vib_eval = f"{vib} mm/s RMS (Zona C ISO 10816 - Alerta Preventiva)"
                    zona = "Zona C"
                else:
                    vib_eval = f"{vib} mm/s RMS (Zona D ISO 10816 - Daño Inminente / Alarma Crítica)"
                    zona = "Zona D"

            return (
                f"**Diagnóstico Técnico para el Activo {tag} ({name})**\n\n"
                f"- **Tipo de Máquina**: {eq_context['equipment_type']}\n"
                f"- **Estado Operacional Actual**: `{status}`\n"
                f"- **Clasificación de Criticidad**: {eq_context['criticality']} (RPN: {eq_context['rpn_score']})\n"
                f"- **Severidad Vibratoria (ISO 10816-3)**: {vib_eval}\n"
                f"- **Temperatura de Operación**: {temp if temp is not None else 'N/D'} °C\n\n"
                f"**Recomendaciones Prescriptivas según SAE JA1011**:\n"
                + (
                    "1. **Atención Inmediata**: La vibración supera el umbral admisible de operación continua. Se aconseja agendar orden de trabajo urgente para inspección boroscópica, verificación de holgura radial en rodamientos y prueba de acoplamiento flexible.\n"
                    if zona in ["Zona C", "Zona D"] else
                    "1. **Condición Estable**: Los parámetros de vibración y térmicos se encuentran dentro del rango permisible de operación continua.\n"
                )
                + "2. Registrar medición espectral FFT en la próxima ronda técnica para verificar armónicos de frecuencia de paso de álabes o pulsación de válvulas.\n"
                "3. Consultar la matriz de modos de falla AMEF asociada en la barra lateral para verificar tareas proactivas programadas."
            )

        # Caso 4: Severidad de vibraciones ISO 10816
        if any(k in clean for k in ["iso 10816", "vibracion", "severidad vibratoria"]):
            return (
                "**Evaluación de Vibraciones Mecánicas en Maquinaria Industrial (Norma ISO 10816-3)**\n\n"
                "La norma ISO 10816-3 evalúa la velocidad cuadrática media (RMS en mm/s) medida sobre soportes y pedestales de rodamientos:\n\n"
                "- **Zona A (< 2.8 mm/s)**: Maquinaria nueva o recién reacondicionada en condiciones óptimas.\n"
                "- **Zona B (2.8 - 4.5 mm/s)**: Máquinas que operan normalmente sin restricciones temporales de servicio.\n"
                "- **Zona C (4.5 - 7.1 mm/s)**: Condición no satisfactoria para operación a largo plazo. Indica deterioro incipiente por desalineación, soltura mecánica o desgaste de rodamientos.\n"
                "- **Zona D (> 7.1 mm/s)**: Daño inminente. Se recomienda la parada planificada inmediata del activo para evitar fallas catastróficas.\n\n"
                "**Nota de Confiabilidad**: Siempre correlacione la vibración con la temperatura del cajetín de rodamientos y el análisis tribológico de aceite lubricante."
            )

        # Caso genérico
        return (
            f"**Asistente Técnico Heimdall RCM**\n\n"
            f"Para su consulta sobre *'{message}'*:\n\n"
            "El sistema de confiabilidad industrial recomienda estructurar el análisis bajo los principios de **SAE JA1011** e **ISO 14224**:\n"
            "1. **Identificación del Activo**: Seleccione o mencione el TAG del equipo (ejemplo: `POZO-BCP-204`, `CMP-001`, `BOM-DCO-102`) para consultar su telemetría en vivo.\n"
            "2. **Monitoreo por Condición**: Verifique los espectros de vibración ISO 10816-3 y temperaturas para ubicar el activo sobre la curva de degradación P-F.\n"
            "3. **Tareas AMEF**: Revise los modos de falla dominantes antes de autorizar el cierre o modificación de órdenes de trabajo.\n\n"
            "Puede formular preguntas como:\n"
            "- *'¿Cómo está el estado del BCP-204?'*\n"
            "- *'¿Qué es RCM según SAE JA1011?'*\n"
            "- *'¿Cuáles son los umbrales de vibración ISO 10816?'*\n"
            "- *'¿Cómo calcular el RPN en un análisis AMEF?'*"
        )

    def _extract_suggestions(self, text: str, eq_context: Optional[Dict[str, Any]]) -> List[str]:
        """Genera sugerencias de navegación y preguntas técnicas coherentes."""
        suggestions = []
        if eq_context:
            tag = eq_context['tag_number']
            suggestions.append(f"Ver matriz AMEF de {tag}")
            suggestions.append(f"Generar plan preventivo para {tag}")
            suggestions.append(f"Consultar telemetría de {tag}")
        else:
            suggestions.append("¿Cuáles son las 7 preguntas de SAE JA1011?")
            suggestions.append("¿Cómo evaluar la vibración bajo ISO 10816?")
            suggestions.append("Evaluar el estado del pozo BCP-204")
            suggestions.append("¿Cómo se calcula el RPN en AMEF?")

        return suggestions[:4]

    def _build_rcm_data(self, text: str, eq_context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Construye un bloque estructurado RCM para renderizado en componentes de UI."""
        if eq_context:
            tag = eq_context['tag_number']
            m = eq_context.get('latest_metric') or {}
            vib = m.get('vibration_mm_s')
            severity = "critical" if vib and vib > 7.1 else ("high" if vib and vib > 4.5 else "low")
            return {
                "equipmentTag": tag,
                "equipmentName": eq_context['name'],
                "criticalityLevel": eq_context['criticality'],
                "vibration_rms": vib,
                "temperature_c": m.get('temperature_celsius'),
                "severity": severity,
                "recommendedTask": "Inspección predictiva y verificación de alineación láser." if severity != "low" else "Monitoreo rutinario por condición."
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
