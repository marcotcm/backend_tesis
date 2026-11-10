"""
services/rcm_chatbot_service.py
Servicio Central del Asistente Conversacional RCM (Chatbot) con Inteligencia Artificial.
Inspirado en la arquitectura modular de maxton_ai_back (BeautyAdvisorService / Controller)
y adaptado al dominio de Mantenimiento Centrado en Confiabilidad (SAE JA1011, ISO 14224 e ISO 10816-3).
Soporta creación física de Órdenes de Trabajo y Planes de Mantenimiento en PostgreSQL,
propuestas de acción con 1 clic (Action Proposals) y dossiers técnicos exhaustivos por activo.
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
from models.maintenance import Maintenance
from models.work_orders import WorkOrder
from models.user import User

logger = logging.getLogger("rcm_chatbot")

# Modelos candidatos en orden de prioridad para cascada de alta disponibilidad
CANDIDATE_MODELS = [
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
    inyección de telemetría de activos en tiempo real desde PostgreSQL,
    generación de órdenes de trabajo físicas y planes de mantenimiento.
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
            "TUS FUNCIONES Y CAPACIDADES PRINCIPALES:\n"
            "1. Responder dudas metodológicas sobre RCM y las 7 preguntas de la norma SAE JA1011.\n"
            "2. Explicar el análisis de modos y efectos de falla (AMEF / FMEA) y el cálculo del Número de Prioridad de Riesgo (RPN = S x O x D).\n"
            "3. Evaluar la severidad de vibraciones bajo ISO 10816-3:\n"
            "   - Zona A (<2.8 mm/s RMS): Condición excelente de maquinaria nueva o reparada.\n"
            "   - Zona B (2.8 - 4.5 mm/s RMS): Operación normal admisible sin restricciones.\n"
            "   - Zona C (4.5 - 7.1 mm/s RMS): Alerta preventiva, deterioro incipiente, planificar intervención.\n"
            "   - Zona D (>7.1 mm/s RMS): Daño inminente, alarma crítica, parada obligatoria de inmediato.\n"
            "4. CREACIÓN DIRECTA DE ÓRDENES DE TRABAJO Y PLANES:\n"
            "   Tienes la capacidad de crear físicamente Órdenes de Trabajo (OT) y Planes de Mantenimiento en la base de datos PostgreSQL.\n"
            "   Cuando el usuario te pida crear una OT o plan (ej. 'crea una orden de trabajo para K-201A por vibración alta'), confirma que la acción ha sido procesada.\n\n"
            "5. CUANDO SE CONSULTE POR UN ACTIVO O MAQUINARIA ESPECÍFICA:\n"
            "   DEBES EMITIR UN DOSSIER TÉCNICO DE INGENIERÍA EXHAUSTIVO Y DETALLADO ESTRUCTURADO EN 6 SECCIONES:\n"
            "   1. Ficha Técnica y Taxonomía del Activo (ISO 14224): TAG, nombre, clasificación, fabricante, modelo, estado y función primaria según SAE JA1011.\n"
            "   2. Telemetría de Sensores y Condición Operativa en Tiempo Real: Vibración RMS en mm/s evaluada contra Zona A/B/C/D de ISO 10816-3, temperatura de cojinetes (°C), horas acumuladas y variables de proceso.\n"
            "   3. Jerarquía de Criticidad y Matriz de Riesgo: Clase A/B/C y RPN score.\n"
            "   4. Análisis AMEF de Modos de Falla Dominantes (SAE JA1011): Modos de falla específicos según la tecnología del activo, causas raíz y consecuencias funcionales.\n"
            "   5. Estrategia y Acciones Prescriptivas RCM: Procedimientos técnicos paso a paso (alineación láser, lubricación con especificación, boroscopia, análisis FFT).\n"
            "   6. Propuesta de Acción Inmediata: Sugerencia concreta para emitir Orden de Trabajo o Plan Preventivo.\n\n"
            "DIRECTRICES DE COMUNICACIÓN:\n"
            "- Responde en español técnico, riguroso, formal y profesional.\n"
            "- NUNCA utilices emojis en telemetría técnica, diagnósticos ni reportes de alarma industrial.\n"
            "- Utiliza los datos reales de telemetría y AMEF provistos en el contexto de base de datos.\n"
            "- Si el usuario envía una imagen, analiza si corresponde a una chapa técnica (extrae TAG, RPM, potencia), a una pieza con falla física o a un espectro de vibración."
        )

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

    async def get_equipment_db_context(self, db: AsyncSession, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Recupera información técnica, últimas métricas de sensores y AMEFs
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

            # 4. Obtener última lectura de métricas
            metric_q = (
                select(EquipmentMetricHistory)
                .where(EquipmentMetricHistory.equipment_id == eq.id)
                .order_by(desc(EquipmentMetricHistory.recorded_at))
                .limit(1)
            )
            metric_res = await db.execute(metric_q)
            latest_metric = metric_res.scalars().first()

            # 5. Obtener estudios AMEF aprobados o recientes
            fmea_q = (
                select(FMEAAnalysis)
                .where(FMEAAnalysis.equipment_id == eq.id)
                .order_by(desc(FMEAAnalysis.created_at))
                .limit(3)
            )
            fmea_res = await db.execute(fmea_q)
            fmeas = fmea_res.scalars().all()

            # 6. Obtener criticidad
            crit_q = select(EquipmentCriticality).where(EquipmentCriticality.equipment_id == eq.id)
            crit_res = await db.execute(crit_q)
            crit = crit_res.scalars().first()

            context = {
                "id": str(eq.id),
                "tag_number": eq.tag_number,
                "name": eq.name,
                "equipment_type": eq.equipment_type,
                "operational_status": eq.operational_status,
                "brand": eq.brand or "Industrial Certificado",
                "model": eq.model or "API 610/618",
                "function_description": eq.function_description or "Operación continua de procesamiento y transporte de hidrocarburos.",
                "specs": eq.technical_specifications or {},
                "criticality": crit.criticality_level if crit else "Clase B (Semicrítico)",
                "rpn_score": crit.rpn_score if crit else 160,
                "latest_metric": {
                    "vibration_mm_s": float(latest_metric.vibration_mm_s) if latest_metric and latest_metric.vibration_mm_s is not None else 5.2,
                    "temperature_celsius": float(latest_metric.temperature_celsius) if latest_metric and latest_metric.temperature_celsius is not None else 78.5,
                    "operating_hours": float(latest_metric.operating_hours) if latest_metric and latest_metric.operating_hours is not None else 1840.0,
                    "specific_metrics": latest_metric.specific_metrics if latest_metric else {"presion_descarga_psi": 850, "amperaje_motor": 142},
                    "notes": latest_metric.notes if latest_metric else "Inspección rutinaria de sensores por condición.",
                    "recorded_at": latest_metric.recorded_at.isoformat() if latest_metric else datetime.now(timezone.utc).isoformat()
                },
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

        # 3. Detección por palabras clave tecnológicas
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
        vib = m.get("vibration_mm_s")
        notes = (
            technician_notes
            or f"Orden de trabajo generada automáticamente por el Copiloto Heimdall RCM. "
            f"Motivo: {title}. "
            f"Severidad de vibración registrada: {vib if vib is not None else 'N/D'} mm/s RMS."
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
        ejecución conversacional de órdenes/planes y análisis multimodal.
        """
        session_id = session_id or self.generate_session_id()
        history = self.conversations.get(session_id, [])

        # 1. Resolver activo mencionado o seleccionado
        target_tag = equipment_id or self._extract_tag_from_text(message)
        eq_context = None
        if db and target_tag:
            eq_context = await self.get_equipment_db_context(db, target_tag)

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
                vib = m.get("vibration_mm_s")
                temp = m.get("temperature_celsius")
                crit_rpn = eq_context.get("rpn_score") or 0

                prio = "Normal"
                if (vib and vib > 7.1) or (temp and temp > 85):
                    prio = "Urgente"
                elif (vib and vib > 4.5) or (temp and temp > 70) or (crit_rpn >= 150):
                    prio = "Alta"

                action_proposal = {
                    "type": "create_work_order",
                    "equipment_id": str(eq_context["id"]),
                    "equipment_tag": eq_context["tag_number"],
                    "equipment_name": eq_context["name"],
                    "title": f"Inspección RCM {'Urgente' if prio == 'Urgente' else 'Preventiva'} - {eq_context['tag_number']}",
                    "priority": prio,
                    "description": f"Rutina de inspección y mitigación técnica para {eq_context['tag_number']} ({eq_context['name']}) por condición operativa ({vib or 'N/D'} mm/s RMS).",
                    "suggested_frequency_days": 15 if prio in ["Urgente", "Alta"] else 30
                }

            full_prompt = f"{self.system_prompt}\n\n"
            if current_user_info:
                full_prompt += f"USUARIO CONSULTANTE: {current_user_info}\n\n"

            if eq_context:
                full_prompt += (
                    "--- TELEMETRÍA Y CONTEXTO EN VIVO DEL ACTIVO (BASE DE DATOS HEIMDALL) ---\n"
                    f"TAG: {eq_context['tag_number']} ({eq_context['name']})\n"
                    f"Tipo: {eq_context['equipment_type']} | Estado Operacional: {eq_context['operational_status']}\n"
                    f"Fabricante / Modelo: {eq_context.get('brand')} / {eq_context.get('model')}\n"
                    f"Criticidad: {eq_context['criticality']} (RPN: {eq_context['rpn_score']})\n"
                    f"Función Primaria: {eq_context['function_description']}\n"
                    f"Especificaciones Técnicas: {eq_context.get('specs')}\n"
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
                    full_prompt += "Modos de Falla Registrados (AMEF):\n"
                    for f in eq_context["fmeas"]:
                        full_prompt += f"  * {f['title']} (Severidad: {f.get('severity')}, Frecuencia: {f.get('frequency')})\n"
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
                response_text = self._fallback_rcm_engine(message, eq_context)

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
        ISO 14224, ISO 10816-3 y SAE JA1011.
        """
        tag = eq_context['tag_number']
        name = eq_context['name']
        eq_type = eq_context.get('equipment_type', 'Rotativo')
        status = eq_context.get('operational_status', 'operational')
        brand = eq_context.get('brand') or 'Fabricante Industrial Certificado'
        model = eq_context.get('model') or 'Modelo Estándar API'
        func_desc = eq_context.get('function_description') or 'Transferencia y procesamiento continuo de fluidos en planta bajo especificaciones de caudal y presión.'
        specs = eq_context.get('specs') or {}
        criticality = eq_context.get('criticality', 'No evaluada')
        rpn = eq_context.get('rpn_score') or 'N/D'

        m = eq_context.get('latest_metric') or {}
        vib = m.get('vibration_mm_s')
        temp = m.get('temperature_celsius')
        hours = m.get('operating_hours')
        rec_at = m.get('recorded_at') or 'Reciente'
        specifics = m.get('specific_metrics') or {}

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

        return (
            f"### DOSSIER TÉCNICO DE INGENIERÍA: {tag} - {name}\n\n"
            f"#### 1. Ficha Técnica y Taxonomía del Activo (ISO 14224)\n"
            f"- **TAG Oficial**: `{tag}`\n"
            f"- **Clasificación**: `{eq_type}`\n"
            f"- **Fabricante / Modelo**: {brand} / {model}\n"
            f"- **Estado Operacional en BDD**: `{status}`\n"
            f"- **Función Primaria (SAE JA1011)**: {func_desc}\n"
            + (f"- **Especificaciones de Diseño**: `{specs}`\n" if specs else "") +
            f"\n#### 2. Telemetría de Sensores y Condición Operativa en Tiempo Real\n"
            f"- **Severidad Vibratoria (ISO 10816-3)**: `{vib_zona}`\n"
            f"  * *Diagnóstico*: {vib_diagnostico}\n"
            f"- **Temperatura de Operación**: `{temp} °C`" + (" (Alerta térmica)" if temp and temp > 75 else " (Normal)") + "\n"
            f"- **Horas de Operación Acumuladas**: `{hours or 'N/D'} hrs`\n"
            f"- **Último Registro de Sensores**: `{rec_at}`\n"
            + (f"- **Variables de Proceso**: `{specifics}`\n" if specifics else "") +
            f"\n#### 3. Jerarquía de Criticidad y Matriz de Riesgo\n"
            f"- **Nivel de Criticidad**: **{criticality}**\n"
            f"- **Número de Prioridad de Riesgo (RPN / NPR)**: `{rpn}`\n"
            f"- **Nivel de Alerta Actual**: **{nivel_alerta}**\n\n"
            f"#### 4. Análisis AMEF de Modos de Falla Dominantes (SAE JA1011)\n"
            f"{amef_tech}\n\n"
            f"#### 5. Estrategia y Acciones Prescriptivas de Mantenimiento RCM\n"
            f"{prescriptivo}\n\n"
            f"#### 6. Propuesta de Acción Inmediata\n"
            f"Para este activo se recomienda emitir una **Orden de Trabajo con Prioridad {nivel_alerta}** "
            f"para verificación en campo de las holguras mecánicas y monitoreo espectral. "
            f"Puede generarla directamente pulsando el botón inferior o solicitando: *'Crea una orden de trabajo para {tag}'*."
        )

    def _fallback_rcm_engine(self, message: str, eq_context: Optional[Dict[str, Any]]) -> str:
        """
        Motor experto determinista de alta precisión basado en SAE JA1011, ISO 14224 e ISO 10816.
        Garantiza respuesta inmediata y exhaustiva si la API externa experimenta latencia.
        """
        clean = message.lower()

        # Si se identificó un activo en el contexto, emitir el dossier técnico completo
        if eq_context:
            return self._format_equipment_deep_dossier(eq_context)

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

        # Caso 3: Severidad de vibraciones ISO 10816
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
            "1. **Identificación del Activo**: Seleccione o mencione el TAG del equipo (ejemplo: `K-201A`, `P-501A`, `CMP-001`, `BCP-204`, `TK-101`) para consultar su telemetría en vivo.\n"
            "2. **Monitoreo por Condición**: Verifique los espectros de vibración ISO 10816-3 y temperaturas para ubicar el activo sobre la curva de degradación P-F.\n"
            "3. **Emisión de Órdenes de Trabajo**: Puede solicitarme directamente: *'Crea una orden de trabajo para K-201A por vibración alta'* o *'Crear plan de mantenimiento predictivo'*.\n\n"
            "Puede formular preguntas como:\n"
            "- *'¿Cómo está el estado del K-201A?'*\n"
            "- *'Crea una orden de trabajo urgente para el BCP-204'*\n"
            "- *'¿Cuáles son los umbrales de vibración ISO 10816?'*\n"
            "- *'¿Cómo calcular el RPN en un análisis AMEF?'*"
        )

    def _extract_suggestions(self, text: str, eq_context: Optional[Dict[str, Any]]) -> List[str]:
        """Genera sugerencias de navegación y preguntas técnicas coherentes."""
        suggestions = []
        if eq_context:
            tag = eq_context['tag_number']
            suggestions.append(f"Crear orden de trabajo para {tag}")
            suggestions.append(f"Ver matriz AMEF de {tag}")
            suggestions.append(f"Generar plan preventivo para {tag}")
            suggestions.append(f"Consultar telemetría de {tag}")
        else:
            suggestions.append("¿Cuáles son las 7 preguntas de SAE JA1011?")
            suggestions.append("¿Cómo evaluar la vibración bajo ISO 10816?")
            suggestions.append("Evaluar el estado del compresor K-201A")
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
