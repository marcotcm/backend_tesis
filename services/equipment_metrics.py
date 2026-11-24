"""
Capa de Servicios y Reglas de Negocio para Métricas de Equipos.

Garantiza la inyección del usuario en sesión, protege la integridad de los 
datos históricos, centraliza la lógica de negocio para las consultas y 
dispara el análisis predictivo de IA ante anomalías físicas.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from crud import equipment_metrics as crud_metrics
from models.equipment import Equipment
from models.equipment_metrics import EquipmentMetricHistory
from models.user import User, UserRole
from schemas.equipment_metrics import EquipmentMetricCreate, EquipmentMetricUpdate
from services.ai_predictive_service import ejecutar_analisis_predictivo_background
from services.industrial_alarms import (
    evaluate_metric_alarms_isa18,
    extract_pressure_psi,
    upsert_hourly_metric_rollup,
)
from services.notification import trigger_global_alert
from services.realtime_twin_hub import twin_hub


def _exceeds_equipment_thresholds(
    equipment: Optional[Equipment],
    temperature_celsius: Optional[float],
    vibration_mm_s: Optional[float],
    specific_metrics: Optional[dict],
) -> bool:
    """Evalúa si la lectura supera límites de `standard_metric` o zona crítica ISO 10816."""
    if vibration_mm_s is not None and vibration_mm_s >= 7.1:
        return True
    if not equipment or not isinstance(equipment.technical_specifications, dict):
        return False

    standard_metric = equipment.technical_specifications.get("standard_metric", {})
    if not isinstance(standard_metric, dict):
        return False

    if "temperature_celsius" in standard_metric and temperature_celsius is not None:
        t_limits = standard_metric["temperature_celsius"]
        if isinstance(t_limits, dict):
            t_min = t_limits.get("min", -50)
            t_max = t_limits.get("max", 1000)
            if temperature_celsius < t_min or temperature_celsius > t_max:
                return True

    if "vibration_mm_s" in standard_metric and vibration_mm_s is not None:
        v_limits = standard_metric["vibration_mm_s"]
        if isinstance(v_limits, dict):
            v_min = v_limits.get("min", 0)
            v_max = v_limits.get("max", 100)
            if vibration_mm_s < v_min or vibration_mm_s > v_max:
                return True

    if isinstance(specific_metrics, dict):
        for var_name, valor_actual in specific_metrics.items():
            if var_name in standard_metric and isinstance(standard_metric[var_name], dict) and valor_actual is not None:
                s_min = standard_metric[var_name].get("min")
                s_max = standard_metric[var_name].get("max")
                try:
                    num_val = float(valor_actual)
                except (ValueError, TypeError):
                    continue
                if s_min is not None and num_val < float(s_min):
                    return True
                if s_max is not None and num_val > float(s_max):
                    return True

    return False


async def record_metric(
    db: AsyncSession,
    metric_in: EquipmentMetricCreate,
    current_user: User,
    background_tasks: BackgroundTasks,
) -> EquipmentMetricHistory:
    """
    Registra una nueva lectura vinculándola al usuario en sesión,
    valida umbrales estándar y dispara la IA en segundo plano si hay anomalía.
    """
    metric_data = metric_in.model_dump()
    metric_data["recorded_by"] = current_user.id

    try:
        # 1. Guardar la métrica en la base de datos
        nueva_metrica = await crud_metrics.create_metric(db, obj_in=metric_data)

        # 2. Consultar el equipo para revisar los umbrales de 'standard_metric'
        eq_result = await db.execute(
            select(Equipment).where(Equipment.id == metric_in.equipment_id)
        )
        equipment = eq_result.scalar_one_or_none()

        # 3. Si se supera algún estándar, lanzar alerta y encolar el análisis con sesión propia
        if _exceeds_equipment_thresholds(
            equipment=equipment,
            temperature_celsius=metric_in.temperature_celsius,
            vibration_mm_s=metric_in.vibration_mm_s,
            specific_metrics=metric_in.specific_metrics,
        ):
            await trigger_global_alert(
                db=db,
                title="⚠️ Alerta: Métrica Anómala Detectada",
                message=f"El equipo {(equipment.tag_number if equipment else None) or metric_in.equipment_id} registró valores fuera de rango operativo normal. Iniciando análisis predictivo IA.",
            )
            await db.commit()

            background_tasks.add_task(
                ejecutar_analisis_predictivo_background,
                equipment_id=metric_in.equipment_id,
                trigger_source="Anomalía en Métrica en Tiempo Real",
                trigger_reference_id=nueva_metrica.id,
            )

        # Fase 2 Enterprise: Evaluación ISA-18.2 y rollup time-series horario (tolerante a tabla no migrada)
        alarm_triggered_evts: List[dict] = []
        alarm_cleared_evts: List[dict] = []
        try:
            async with db.begin_nested():
                trig, clrd = await evaluate_metric_alarms_isa18(
                    db=db,
                    equipment=equipment,
                    temperature_celsius=float(metric_in.temperature_celsius)
                    if metric_in.temperature_celsius is not None
                    else None,
                    vibration_mm_s=float(metric_in.vibration_mm_s)
                    if metric_in.vibration_mm_s is not None
                    else None,
                    specific_metrics=metric_in.specific_metrics,
                )
                alarm_triggered_evts.extend(trig)
                alarm_cleared_evts.extend(clrd)
                await upsert_hourly_metric_rollup(
                    db=db,
                    equipment_id=metric_in.equipment_id,
                    recorded_at=nueva_metrica.recorded_at,
                    temperature_celsius=float(metric_in.temperature_celsius)
                    if metric_in.temperature_celsius is not None
                    else None,
                    vibration_mm_s=float(metric_in.vibration_mm_s)
                    if metric_in.vibration_mm_s is not None
                    else None,
                    pressure_psi=extract_pressure_psi(metric_in.specific_metrics),
                )
            await db.commit()
        except Exception as phase2_err:
            print(f"[WARN PHASE2 METRIC HOOK] {phase2_err}")

        tax_str = str(equipment.taxonomy_id) if equipment and equipment.taxonomy_id else None
        for evt in alarm_triggered_evts:
            await twin_hub.broadcast_event("alarm_triggered", evt, taxonomy_id=tax_str)
        for evt in alarm_cleared_evts:
            await twin_hub.broadcast_event("alarm_cleared", evt, taxonomy_id=tax_str)

        await twin_hub.broadcast_event(
            "metric_ingested",
            {
                "equipment_id": str(metric_in.equipment_id),
                "tag_number": equipment.tag_number if equipment else None,
                "metric_id": str(nueva_metrica.id),
            },
            taxonomy_id=tax_str,
        )

        return nueva_metrica

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fallo al registrar la métrica en la base de datos: {str(e)}",
        )


async def ingest_iot_batch(
    db: AsyncSession,
    source: str,
    readings: List[dict],
    actor_user_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Ingesta industrial de alta frecuencia referenciada por TAG de planta (o UUID).
    Inserta el lote en `equipment_metrics_history` y transmite actualización WebSocket <100ms.
    """
    eq_rows = (
        await db.execute(
            select(Equipment).where(Equipment.is_active == True, Equipment.deleted_at.is_(None))
        )
    ).scalars().all()

    by_id = {eq.id: eq for eq in eq_rows}
    by_tag = {str(eq.tag_number or "").strip().upper(): eq for eq in eq_rows if eq.tag_number}

    created_objs: List[EquipmentMetricHistory] = []
    matched_eqs: List[Equipment] = []
    unmatched_tags: List[str] = []

    for item in readings:
        eq = None
        if item.get("equipment_id"):
            eq = by_id.get(item["equipment_id"])
        if not eq and item.get("tag_number"):
            tag_key = str(item["tag_number"]).strip().upper()
            eq = by_tag.get(tag_key)

        if not eq:
            unmatched_tags.append(str(item.get("tag_number") or item.get("equipment_id") or "DESCONOCIDO"))
            continue

        spec = dict(item.get("specific_metrics") or {})
        if item.get("pressure_psi") is not None:
            spec["presion_descarga_psi"] = float(item["pressure_psi"])
        if item.get("flow_rate_bpd") is not None:
            spec["caudal_bpd"] = float(item["flow_rate_bpd"])
        if item.get("motor_amps") is not None:
            spec["motorAmps"] = float(item["motor_amps"])
        if item.get("liquid_level_pct") is not None:
            spec["liquid_level_percentage"] = float(item["liquid_level_pct"])
        if item.get("rpm") is not None:
            spec["velocidad_rpm"] = float(item["rpm"])

        op_hours = item.get("operating_hours")
        if op_hours is None:
            op_hours = round(float(eq.usage_time or 0) / 60.0, 2)

        metric_obj = EquipmentMetricHistory(
            equipment_id=eq.id,
            temperature_celsius=item.get("temperature_celsius"),
            vibration_mm_s=item.get("vibration_mm_s"),
            operating_hours=op_hours,
            specific_metrics=spec,
            notes=item.get("notes") or f"Telemetría IoT ({source})",
            recorded_by=actor_user_id,
        )
        created_objs.append(metric_obj)
        matched_eqs.append(eq)

    if not created_objs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ningún TAG coincide con equipos activos en planta ({', '.join(unmatched_tags[:5])}).",
        )

    db.add_all(created_objs)
    await db.commit()

    anomalous_eq_ids: set[uuid.UUID] = set()
    for eq, metric_obj in zip(matched_eqs, created_objs):
        await db.refresh(metric_obj)
        if eq.id not in anomalous_eq_ids and _exceeds_equipment_thresholds(
            equipment=eq,
            temperature_celsius=float(metric_obj.temperature_celsius) if metric_obj.temperature_celsius is not None else None,
            vibration_mm_s=float(metric_obj.vibration_mm_s) if metric_obj.vibration_mm_s is not None else None,
            specific_metrics=metric_obj.specific_metrics,
        ):
            anomalous_eq_ids.add(eq.id)
            background_tasks.add_task(
                ejecutar_analisis_predictivo_background,
                equipment_id=eq.id,
                trigger_source=f"IoT Gateway ({source})",
                trigger_reference_id=metric_obj.id,
            )

    batch_triggered: List[tuple[Optional[str], dict]] = []
    batch_cleared: List[tuple[Optional[str], dict]] = []
    try:
        async with db.begin_nested():
            for eq, metric_obj in zip(matched_eqs, created_objs):
                temp_v = float(metric_obj.temperature_celsius) if metric_obj.temperature_celsius is not None else None
                vib_v = float(metric_obj.vibration_mm_s) if metric_obj.vibration_mm_s is not None else None
                trig, clrd = await evaluate_metric_alarms_isa18(
                    db=db,
                    equipment=eq,
                    temperature_celsius=temp_v,
                    vibration_mm_s=vib_v,
                    specific_metrics=metric_obj.specific_metrics,
                )
                tax_str = str(eq.taxonomy_id) if eq.taxonomy_id else None
                for evt in trig:
                    batch_triggered.append((tax_str, evt))
                for evt in clrd:
                    batch_cleared.append((tax_str, evt))

                await upsert_hourly_metric_rollup(
                    db=db,
                    equipment_id=eq.id,
                    recorded_at=metric_obj.recorded_at,
                    temperature_celsius=temp_v,
                    vibration_mm_s=vib_v,
                    pressure_psi=extract_pressure_psi(metric_obj.specific_metrics),
                )
        await db.commit()
    except Exception as phase2_batch_err:
        print(f"[WARN PHASE2 IOT HOOK] {phase2_batch_err}")

    for tax_str, evt in batch_triggered:
        await twin_hub.broadcast_event("alarm_triggered", evt, taxonomy_id=tax_str)
    for tax_str, evt in batch_cleared:
        await twin_hub.broadcast_event("alarm_cleared", evt, taxonomy_id=tax_str)

    tags_updated = list({eq.tag_number for eq in matched_eqs})
    equipment_ids = list({str(eq.id) for eq in matched_eqs})

    await twin_hub.broadcast_event(
        "iot_batch_ingested",
        {
            "source": source,
            "ingested_count": len(created_objs),
            "tags": tags_updated,
            "equipment_ids": equipment_ids,
        },
    )

    return {
        "source": source,
        "ingested_count": len(created_objs),
        "unmatched_tags": unmatched_tags,
        "tags_updated": tags_updated,
    }


# ==========================================
# FUNCIONES DE SERVICIO PARA LECTURA
# ==========================================
async def get_all_metrics(
    db: AsyncSession, skip: int, limit: int
) -> List[EquipmentMetricHistory]:
    """Servicio para obtener el historial global."""
    return await crud_metrics.get_metrics(db, skip=skip, limit=limit)


async def get_equipment_metrics(
    db: AsyncSession, equipment_id: uuid.UUID, skip: int, limit: int
) -> List[EquipmentMetricHistory]:
    """Servicio para obtener la tendencia de un equipo."""
    return await crud_metrics.get_metrics_by_equipment(
        db, equipment_id=equipment_id, skip=skip, limit=limit
    )


async def get_user_metrics(
    db: AsyncSession, user_id: uuid.UUID, skip: int, limit: int
) -> List[EquipmentMetricHistory]:
    """Servicio para obtener las lecturas registradas por un técnico."""
    return await crud_metrics.get_metrics_by_user(
        db, user_id=user_id, skip=skip, limit=limit
    )


async def get_metrics_by_dates(
    db: AsyncSession,
    start_date: datetime,
    end_date: datetime,
    equipment_id: Optional[uuid.UUID],
    skip: int,
    limit: int,
) -> List[EquipmentMetricHistory]:
    """Servicio para filtrar métricas por fechas con validación de negocio."""
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error de negocio: La fecha de inicio no puede ser posterior a la fecha de fin.",
        )
    return await crud_metrics.get_metrics_by_date_range(
        db, start_date, end_date, equipment_id, skip, limit
    )


async def get_metric_or_404(
    db: AsyncSession, metric_id: uuid.UUID
) -> EquipmentMetricHistory:
    """Obtiene una lectura o genera un error 404 estructurado."""
    metric = await crud_metrics.get_metric_by_id(db, metric_id)
    if not metric:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registro de métrica no encontrado.",
        )
    return metric


async def update_metric_record(
    db: AsyncSession,
    metric_id: uuid.UUID,
    metric_in: EquipmentMetricUpdate,
    current_user: User,
) -> EquipmentMetricHistory:
    """Aplica una actualización restringida a una métrica existente."""
    db_metric = await get_metric_or_404(db, metric_id)

    if (
        current_user.role != UserRole.admin
        and db_metric.recorded_by != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para modificar una métrica registrada por otro técnico.",
        )

    update_data = metric_in.model_dump(exclude_unset=True)
    if not update_data:
        return db_metric

    return await crud_metrics.update_metric(
        db, db_obj=db_metric, update_data=update_data
    )


async def delete_metric_record(
    db: AsyncSession, metric_id: uuid.UUID, current_user: User
) -> dict:
    """Elimina físicamente una lectura errónea. Restringido exclusivamente a administradores."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los administradores pueden eliminar registros históricos del sistema.",
        )

    db_metric = await get_metric_or_404(db, metric_id)
    await crud_metrics.delete_metric(db, db_obj=db_metric)

    return {"detail": "Registro histórico de métrica eliminado permanentemente."}