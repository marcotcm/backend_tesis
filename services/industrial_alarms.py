"""
Motor de Alarmas Industriales ISA-18.2 (con deduplicación y ciclo de vida ACK/Shelve)
y Rollups Time-Series horarios para consultas de 24h / 7d / 30d.
"""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.equipment import Equipment
from models.equipment_metrics import EquipmentMetricHistory
from models.industrial_alarm import EquipmentMetricHourly, IndustrialAlarm
from models.user import User
from schemas.industrial_alarm import (
    AlarmAckRequest,
    AlarmShelveRequest,
    AlarmsSummary,
    IndustrialAlarmResponse,
    MetricTimeSeriesPoint,
)
from services.realtime_twin_hub import twin_hub

OPEN_ALARM_STATES = ("ACTIVE_UNACK", "ACTIVE_ACK", "SHELVED")
PRIORITY_RANK = {"P1_CRITICAL": 1, "P2_HIGH": 2, "P3_MEDIUM": 3, "P4_LOW": 4}


def extract_pressure_psi(specific_metrics: Optional[dict]) -> Optional[float]:
    if not isinstance(specific_metrics, dict):
        return None
    for key in (
        "presion_descarga_psi",
        "pressure_psi",
        "internal_pressure_psi",
        "Presión de descarga (psig)",
    ):
        val = specific_metrics.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _inspect_metric_conditions(
    equipment: Optional[Equipment],
    temperature_celsius: Optional[float],
    vibration_mm_s: Optional[float],
    specific_metrics: Optional[dict],
) -> Dict[str, Dict[str, Any]]:
    """Evalúa cada variable física y retorna si está en alarma o en rango normal."""
    specs = equipment.technical_specifications if equipment and isinstance(equipment.technical_specifications, dict) else {}
    std = specs.get("standard_metric", {})
    if not isinstance(std, dict):
        std = {}

    tag = equipment.tag_number if equipment else "ACTIVO"
    conditions: Dict[str, Dict[str, Any]] = {}

    if vibration_mm_s is not None:
        v_cfg = std.get("vibration_mm_s") if isinstance(std.get("vibration_mm_s"), dict) else {}
        v_max = float(v_cfg.get("max", 4.5) or 4.5)
        if vibration_mm_s >= 7.1:
            conditions["vibration_mm_s"] = {
                "violated": True,
                "priority": "P1_CRITICAL",
                "value": float(vibration_mm_s),
                "threshold": 7.1,
                "message": f"{tag}: Vibración crítica ({vibration_mm_s:.2f} mm/s ≥ 7.1 mm/s ISO 10816-3)",
            }
        elif vibration_mm_s > v_max or vibration_mm_s >= 4.5:
            thr = min(v_max, 4.5) if v_max > 0 else 4.5
            conditions["vibration_mm_s"] = {
                "violated": True,
                "priority": "P2_HIGH",
                "value": float(vibration_mm_s),
                "threshold": thr,
                "message": f"{tag}: Vibración elevada ({vibration_mm_s:.2f} mm/s > {thr:.2f} mm/s)",
            }
        else:
            conditions["vibration_mm_s"] = {"violated": False}

    if temperature_celsius is not None:
        t_cfg = std.get("temperature_celsius") if isinstance(std.get("temperature_celsius"), dict) else {}
        t_max = float(t_cfg.get("max", 85.0) or 85.0)
        t_min = float(t_cfg.get("min", -20.0) if t_cfg.get("min") is not None else -20.0)
        if temperature_celsius >= max(95.0, t_max * 1.15):
            conditions["temperature_celsius"] = {
                "violated": True,
                "priority": "P1_CRITICAL",
                "value": float(temperature_celsius),
                "threshold": round(max(95.0, t_max * 1.15), 1),
                "message": f"{tag}: Sobretemperatura crítica ({temperature_celsius:.1f} °C)",
            }
        elif temperature_celsius > t_max or temperature_celsius >= 80.0:
            thr = min(t_max, 80.0) if t_max > 0 else 80.0
            conditions["temperature_celsius"] = {
                "violated": True,
                "priority": "P2_HIGH",
                "value": float(temperature_celsius),
                "threshold": thr,
                "message": f"{tag}: Temperatura alta ({temperature_celsius:.1f} °C > {thr:.1f} °C)",
            }
        elif temperature_celsius < t_min:
            conditions["temperature_celsius"] = {
                "violated": True,
                "priority": "P3_MEDIUM",
                "value": float(temperature_celsius),
                "threshold": t_min,
                "message": f"{tag}: Temperatura bajo mínimo ({temperature_celsius:.1f} °C < {t_min:.1f} °C)",
            }
        else:
            conditions["temperature_celsius"] = {"violated": False}

    if isinstance(specific_metrics, dict):
        for var_name, val in specific_metrics.items():
            if var_name in ("temperature_celsius", "vibration_mm_s") or val is None:
                continue
            lim = std.get(var_name)
            if not isinstance(lim, dict):
                continue
            try:
                num_val = float(val)
            except (TypeError, ValueError):
                continue
            s_min = lim.get("min")
            s_max = lim.get("max")
            if s_max is not None and num_val > float(s_max):
                conditions[var_name] = {
                    "violated": True,
                    "priority": "P2_HIGH",
                    "value": num_val,
                    "threshold": float(s_max),
                    "message": f"{tag}: {var_name} ({num_val:.1f}) supera límite máximo ({float(s_max):.1f})",
                }
            elif s_min is not None and num_val < float(s_min):
                conditions[var_name] = {
                    "violated": True,
                    "priority": "P2_HIGH",
                    "value": num_val,
                    "threshold": float(s_min),
                    "message": f"{tag}: {var_name} ({num_val:.1f}) bajo límite mínimo ({float(s_min):.1f})",
                }
            else:
                conditions[var_name] = {"violated": False}

    return conditions


async def evaluate_metric_alarms_isa18(
    db: AsyncSession,
    equipment: Optional[Equipment],
    temperature_celsius: Optional[float],
    vibration_mm_s: Optional[float],
    specific_metrics: Optional[dict],
) -> Tuple[List[dict], List[dict]]:
    """
    Evalúa máquina de estados ISA-18.2 con deduplicación anti-inundación.
    Retorna (triggered_events, cleared_events) para difusión WebSocket tras commit.
    """
    if not equipment:
        return [], []

    conditions = _inspect_metric_conditions(
        equipment=equipment,
        temperature_celsius=temperature_celsius,
        vibration_mm_s=vibration_mm_s,
        specific_metrics=specific_metrics,
    )
    if not conditions:
        return [], []

    now = datetime.now(timezone.utc)
    open_rows = (
        await db.execute(
            select(IndustrialAlarm).where(
                IndustrialAlarm.equipment_id == equipment.id,
                IndustrialAlarm.state.in_(OPEN_ALARM_STATES),
            )
        )
    ).scalars().all()
    open_by_key = {row.metric_key: row for row in open_rows}

    triggered_events: List[dict] = []
    cleared_events: List[dict] = []

    for metric_key, cond in conditions.items():
        existing = open_by_key.get(metric_key)
        if cond["violated"]:
            val_dec = Decimal(str(round(float(cond["value"]), 3)))
            thr_dec = Decimal(str(round(float(cond["threshold"]), 3)))
            if existing:
                existing.occurrence_count = int(existing.occurrence_count or 1) + 1
                existing.trigger_value = val_dec
                existing.threshold_value = thr_dec
                existing.message = cond["message"]
                existing.last_seen_at = now
                existing.updated_at = now
                if PRIORITY_RANK.get(cond["priority"], 9) < PRIORITY_RANK.get(existing.priority, 9):
                    existing.priority = cond["priority"]
                if existing.state == "SHELVED" and existing.shelved_until and existing.shelved_until <= now:
                    existing.state = "ACTIVE_UNACK"
                    existing.shelved_until = None
                    triggered_events.append(
                        {
                            "alarm_id": str(existing.id),
                            "equipment_id": str(equipment.id),
                            "tag_number": equipment.tag_number,
                            "priority": existing.priority,
                        }
                    )
                db.add(existing)
            else:
                new_alarm = IndustrialAlarm(
                    equipment_id=equipment.id,
                    metric_key=metric_key,
                    state="ACTIVE_UNACK",
                    priority=cond["priority"],
                    message=cond["message"],
                    trigger_value=val_dec,
                    threshold_value=thr_dec,
                    occurrence_count=1,
                    triggered_at=now,
                    last_seen_at=now,
                    updated_at=now,
                )
                db.add(new_alarm)
                await db.flush()
                triggered_events.append(
                    {
                        "alarm_id": str(new_alarm.id),
                        "equipment_id": str(equipment.id),
                        "tag_number": equipment.tag_number,
                        "priority": new_alarm.priority,
                    }
                )
        else:
            if existing:
                next_state = "CLEARED_ACK" if existing.state == "ACTIVE_ACK" else "CLEARED_UNACK"
                existing.state = next_state
                existing.cleared_at = now
                existing.shelved_until = None
                existing.updated_at = now
                db.add(existing)
                cleared_events.append(
                    {
                        "alarm_id": str(existing.id),
                        "equipment_id": str(equipment.id),
                        "tag_number": equipment.tag_number,
                        "state": next_state,
                    }
                )

    return triggered_events, cleared_events


async def upsert_hourly_metric_rollup(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    recorded_at: Optional[datetime],
    temperature_celsius: Optional[float],
    vibration_mm_s: Optional[float],
    pressure_psi: Optional[float],
) -> None:
    """Actualiza el rollup horario pre-agregado en PostgreSQL de forma incremental."""
    ts = recorded_at or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    bucket_hour = ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    now = datetime.now(timezone.utc)

    vib_dec = Decimal(str(round(float(vibration_mm_s), 3))) if vibration_mm_s is not None else None
    temp_dec = Decimal(str(round(float(temperature_celsius), 3))) if temperature_celsius is not None else None
    press_dec = Decimal(str(round(float(pressure_psi), 3))) if pressure_psi is not None else None

    stmt = pg_insert(EquipmentMetricHourly).values(
        equipment_id=equipment_id,
        bucket_hour=bucket_hour,
        sample_count=1,
        avg_vibration=vib_dec,
        max_vibration=vib_dec,
        avg_temperature=temp_dec,
        max_temperature=temp_dec,
        avg_pressure=press_dec,
        max_pressure=press_dec,
        updated_at=now,
    )

    def _avg_expr(col, excl_col):
        return case(
            (excl_col.is_(None), col),
            (col.is_(None), excl_col),
            else_=((col * EquipmentMetricHourly.sample_count) + excl_col)
            / (EquipmentMetricHourly.sample_count + stmt.excluded.sample_count),
        )

    def _max_expr(col, excl_col):
        return func.coalesce(func.greatest(col, excl_col), col, excl_col)

    stmt = stmt.on_conflict_do_update(
        index_elements=["equipment_id", "bucket_hour"],
        set_={
            "sample_count": EquipmentMetricHourly.sample_count + stmt.excluded.sample_count,
            "avg_vibration": _avg_expr(EquipmentMetricHourly.avg_vibration, stmt.excluded.avg_vibration),
            "max_vibration": _max_expr(EquipmentMetricHourly.max_vibration, stmt.excluded.max_vibration),
            "avg_temperature": _avg_expr(EquipmentMetricHourly.avg_temperature, stmt.excluded.avg_temperature),
            "max_temperature": _max_expr(EquipmentMetricHourly.max_temperature, stmt.excluded.max_temperature),
            "avg_pressure": _avg_expr(EquipmentMetricHourly.avg_pressure, stmt.excluded.avg_pressure),
            "max_pressure": _max_expr(EquipmentMetricHourly.max_pressure, stmt.excluded.max_pressure),
            "updated_at": now,
        },
    )
    await db.execute(stmt)


def _format_alarm_response(alarm: IndustrialAlarm, eq: Equipment, ack_user: Optional[User]) -> IndustrialAlarmResponse:
    ack_name = None
    if ack_user:
        full_name = f"{ack_user.first_name or ''} {ack_user.last_name or ''}".strip()
        ack_name = full_name or ack_user.email
    return IndustrialAlarmResponse(
        id=alarm.id,
        equipment_id=alarm.equipment_id,
        equipment_tag=eq.tag_number,
        equipment_name=eq.name,
        metric_key=alarm.metric_key,
        state=alarm.state,
        priority=alarm.priority,
        message=alarm.message,
        trigger_value=float(alarm.trigger_value) if alarm.trigger_value is not None else None,
        threshold_value=float(alarm.threshold_value) if alarm.threshold_value is not None else None,
        occurrence_count=int(alarm.occurrence_count or 1),
        acknowledged_by=alarm.acknowledged_by,
        acknowledged_by_name=ack_name,
        acknowledged_at=alarm.acknowledged_at,
        ack_notes=alarm.ack_notes,
        shelved_until=alarm.shelved_until,
        triggered_at=alarm.triggered_at,
        last_seen_at=alarm.last_seen_at,
        cleared_at=alarm.cleared_at,
    )


async def list_alarms(
    db: AsyncSession,
    state: Optional[str] = None,
    priority: Optional[str] = None,
    equipment_id: Optional[uuid.UUID] = None,
    include_cleared: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> List[IndustrialAlarmResponse]:
    try:
        stmt = (
            select(IndustrialAlarm, Equipment, User)
            .join(Equipment, Equipment.id == IndustrialAlarm.equipment_id)
            .outerjoin(User, User.id == IndustrialAlarm.acknowledged_by)
        )
        if state:
            stmt = stmt.where(IndustrialAlarm.state == state)
        elif not include_cleared:
            stmt = stmt.where(IndustrialAlarm.state.in_(["ACTIVE_UNACK", "ACTIVE_ACK", "CLEARED_UNACK", "SHELVED"]))

        if priority:
            stmt = stmt.where(IndustrialAlarm.priority == priority)
        if equipment_id:
            stmt = stmt.where(IndustrialAlarm.equipment_id == equipment_id)

        state_order = case(
            (IndustrialAlarm.state == "ACTIVE_UNACK", 0),
            (IndustrialAlarm.state == "ACTIVE_ACK", 1),
            (IndustrialAlarm.state == "CLEARED_UNACK", 2),
            (IndustrialAlarm.state == "SHELVED", 3),
            else_=4,
        )
        prio_order = case(
            (IndustrialAlarm.priority == "P1_CRITICAL", 0),
            (IndustrialAlarm.priority == "P2_HIGH", 1),
            (IndustrialAlarm.priority == "P3_MEDIUM", 2),
            else_=3,
        )
        stmt = (
            stmt.order_by(state_order, prio_order, IndustrialAlarm.triggered_at.desc())
            .offset(skip)
            .limit(limit)
        )
        res = await db.execute(stmt)
        return [_format_alarm_response(alarm, eq, ack_u) for alarm, eq, ack_u in res.all()]
    except Exception:
        await db.rollback()
        return []


async def get_alarms_summary(db: AsyncSession) -> AlarmsSummary:
    try:
        res = await db.execute(
            select(
                func.count(case((IndustrialAlarm.state == "ACTIVE_UNACK", 1))).label("active_unack"),
                func.count(case((IndustrialAlarm.state == "ACTIVE_ACK", 1))).label("active_ack"),
                func.count(case((IndustrialAlarm.state == "CLEARED_UNACK", 1))).label("cleared_unack"),
                func.count(case((IndustrialAlarm.state == "SHELVED", 1))).label("shelved"),
                func.count(
                    case(
                        (
                            (IndustrialAlarm.priority == "P1_CRITICAL")
                            & IndustrialAlarm.state.in_(["ACTIVE_UNACK", "ACTIVE_ACK"]),
                            1,
                        )
                    )
                ).label("p1_active"),
            )
        )
        row = res.mappings().one()
        return AlarmsSummary(
            active_unack=int(row["active_unack"] or 0),
            active_ack=int(row["active_ack"] or 0),
            cleared_unack=int(row["cleared_unack"] or 0),
            shelved=int(row["shelved"] or 0),
            p1_active=int(row["p1_active"] or 0),
        )
    except Exception:
        await db.rollback()
        return AlarmsSummary()


async def acknowledge_alarm(
    db: AsyncSession,
    alarm_id: uuid.UUID,
    ack_req: AlarmAckRequest,
    current_user: User,
) -> IndustrialAlarmResponse:
    res = await db.execute(
        select(IndustrialAlarm, Equipment)
        .join(Equipment, Equipment.id == IndustrialAlarm.equipment_id)
        .where(IndustrialAlarm.id == alarm_id)
    )
    pair = res.first()
    if not pair:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alarma no encontrada.")
    alarm, eq = pair

    now = datetime.now(timezone.utc)
    if alarm.state in ("CLEARED_UNACK", "CLEARED_ACK"):
        alarm.state = "CLEARED_ACK"
    else:
        alarm.state = "ACTIVE_ACK"

    alarm.acknowledged_by = current_user.id
    alarm.acknowledged_at = now
    if ack_req.ack_notes:
        alarm.ack_notes = ack_req.ack_notes.strip()
    alarm.updated_at = now

    db.add(alarm)
    await db.commit()
    await db.refresh(alarm)

    await twin_hub.broadcast_event(
        "alarm_acknowledged",
        {"alarm_id": str(alarm.id), "equipment_id": str(eq.id), "state": alarm.state},
        taxonomy_id=str(eq.taxonomy_id) if eq.taxonomy_id else None,
    )
    return _format_alarm_response(alarm, eq, current_user)


async def shelve_alarm(
    db: AsyncSession,
    alarm_id: uuid.UUID,
    shelve_req: AlarmShelveRequest,
    current_user: User,
) -> IndustrialAlarmResponse:
    res = await db.execute(
        select(IndustrialAlarm, Equipment)
        .join(Equipment, Equipment.id == IndustrialAlarm.equipment_id)
        .where(IndustrialAlarm.id == alarm_id)
    )
    pair = res.first()
    if not pair:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alarma no encontrada.")
    alarm, eq = pair

    now = datetime.now(timezone.utc)
    alarm.state = "SHELVED"
    alarm.shelved_until = now + timedelta(hours=float(shelve_req.hours))
    alarm.acknowledged_by = current_user.id
    alarm.acknowledged_at = now
    if shelve_req.reason:
        alarm.ack_notes = f"Silenciada ({shelve_req.hours}h): {shelve_req.reason.strip()}"
    alarm.updated_at = now

    db.add(alarm)
    await db.commit()
    await db.refresh(alarm)

    await twin_hub.broadcast_event(
        "alarm_acknowledged",
        {"alarm_id": str(alarm.id), "equipment_id": str(eq.id), "state": alarm.state},
        taxonomy_id=str(eq.taxonomy_id) if eq.taxonomy_id else None,
    )
    return _format_alarm_response(alarm, eq, current_user)


async def get_equipment_timeseries(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    range_key: str = "24h",
) -> List[MetricTimeSeriesPoint]:
    hours_map = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}
    hours = hours_map.get(range_key, 24)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # 1. Intentar leer desde rollups horarios pre-agregados
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(EquipmentMetricHourly)
                    .where(
                        EquipmentMetricHourly.equipment_id == equipment_id,
                        EquipmentMetricHourly.bucket_hour >= since,
                    )
                    .order_by(EquipmentMetricHourly.bucket_hour.asc())
                )
            ).scalars().all()
            if rows:
                return [
                    MetricTimeSeriesPoint(
                        bucket=r.bucket_hour,
                        vibration_mm_s=round(float(r.avg_vibration), 2) if r.avg_vibration is not None else None,
                        max_vibration_mm_s=round(float(r.max_vibration), 2) if r.max_vibration is not None else None,
                        temperature_celsius=round(float(r.avg_temperature), 1) if r.avg_temperature is not None else None,
                        max_temperature_celsius=round(float(r.max_temperature), 1) if r.max_temperature is not None else None,
                        pressure_psi=round(float(r.avg_pressure), 1) if r.avg_pressure is not None else None,
                        sample_count=int(r.sample_count or 0),
                    )
                    for r in rows
                ]
    except Exception:
        pass

    # 2. Fallback transparente agregando desde lecturas históricas reales
    raw_rows = (
        await db.execute(
            select(EquipmentMetricHistory)
            .where(
                EquipmentMetricHistory.equipment_id == equipment_id,
                EquipmentMetricHistory.recorded_at >= since,
            )
            .order_by(EquipmentMetricHistory.recorded_at.asc())
        )
    ).scalars().all()

    buckets: Dict[datetime, Dict[str, Any]] = defaultdict(
        lambda: {"vibs": [], "temps": [], "press": [], "count": 0}
    )
    for m in raw_rows:
        ts = m.recorded_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        b_hour = ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        entry = buckets[b_hour]
        entry["count"] += 1
        if m.vibration_mm_s is not None:
            entry["vibs"].append(float(m.vibration_mm_s))
        if m.temperature_celsius is not None:
            entry["temps"].append(float(m.temperature_celsius))
        p_val = extract_pressure_psi(m.specific_metrics)
        if p_val is not None:
            entry["press"].append(p_val)

    points: List[MetricTimeSeriesPoint] = []
    for b_hour in sorted(buckets.keys()):
        entry = buckets[b_hour]
        vibs = entry["vibs"]
        temps = entry["temps"]
        press = entry["press"]
        points.append(
            MetricTimeSeriesPoint(
                bucket=b_hour,
                vibration_mm_s=round(sum(vibs) / len(vibs), 2) if vibs else None,
                max_vibration_mm_s=round(max(vibs), 2) if vibs else None,
                temperature_celsius=round(sum(temps) / len(temps), 1) if temps else None,
                max_temperature_celsius=round(max(temps), 1) if temps else None,
                pressure_psi=round(sum(press) / len(press), 1) if press else None,
                sample_count=entry["count"],
            )
        )
    return points
