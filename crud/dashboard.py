from datetime import datetime
from typing import Any

from sqlalchemy import case, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai_recommendation import AIRecommendation
from models.equipment import Equipment
from models.equipment_criticality import EquipmentCriticality
from models.failure_history import FailureHistory
from models.maintenance import Maintenance
from models.maintenance_history import MaintenanceHistory
from models.work_orders import WorkOrder, WorkOrderStatus


async def get_equipment_stats(db: AsyncSession) -> dict[str, int]:
    active_equipment = Equipment.is_active.is_(True) & Equipment.deleted_at.is_(None)
    result = await db.execute(
        select(
            func.count(Equipment.id).label("total"),
            func.count(
                case(
                    (
                        active_equipment
                        & (Equipment.operational_status == "operational"),
                        1,
                    )
                )
            ).label("operational"),
            func.count(
                case(
                    (
                        active_equipment
                        & (Equipment.operational_status == "standby"),
                        1,
                    )
                )
            ).label("standby"),
            func.count(
                case(
                    (
                        active_equipment
                        & (Equipment.operational_status == "under_maintenance"),
                        1,
                    )
                )
            ).label("under_maintenance"),
            func.count(
                case(
                    (
                        active_equipment & (Equipment.operational_status == "failed"),
                        1,
                    )
                )
            ).label("failed"),
            func.count(
                case(
                    (
                        Equipment.is_active.is_(False)
                        | Equipment.deleted_at.is_not(None),
                        1,
                    )
                )
            ).label("inactive"),
        )
    )
    stats = dict(result.mappings().one())

    critical_result = await db.execute(
        select(func.count(Equipment.id))
        .join(
            EquipmentCriticality,
            EquipmentCriticality.equipment_id == Equipment.id,
        )
        .where(
            active_equipment,
            EquipmentCriticality.criticality_level == "Alta",
        )
    )
    stats["critical"] = critical_result.scalar_one()
    return stats


async def get_work_order_stats(
    db: AsyncSession,
    now: datetime,
    month_start: datetime,
    next_month_start: datetime,
) -> dict[str, int]:
    pending = WorkOrder.status == WorkOrderStatus.pendiente
    in_progress = WorkOrder.status == WorkOrderStatus.en_proceso
    active = pending | in_progress
    result = await db.execute(
        select(
            func.count(case((active, 1))).label("total_active"),
            func.count(case((pending, 1))).label("pending"),
            func.count(case((in_progress, 1))).label("in_progress"),
            func.count(
                case(
                    (
                        (WorkOrder.status == WorkOrderStatus.terminado)
                        & (WorkOrder.completed_at >= month_start)
                        & (WorkOrder.completed_at < next_month_start),
                        1,
                    )
                )
            ).label("completed_this_month"),
            func.count(
                case(
                    (
                        active
                        & WorkOrder.scheduled_for.is_not(None)
                        & (WorkOrder.scheduled_for < now),
                        1,
                    )
                )
            ).label("overdue"),
        )
    )
    return dict(result.mappings().one())


async def get_failure_stats(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        select(
            func.count(FailureHistory.id).label("total_recorded"),
            func.avg(FailureHistory.downtime_hours).label(
                "average_downtime_hours"
            ),
            func.coalesce(func.sum(FailureHistory.downtime_hours), 0.0).label(
                "total_downtime_hours"
            ),
        )
    )
    failure_row = dict(result.mappings().one())

    active_equipment = Equipment.is_active.is_(True) & Equipment.deleted_at.is_(None)
    op_result = await db.execute(
        select(
            func.count(Equipment.id).label("active_count"),
            func.coalesce(func.sum(Equipment.usage_time), 0).label("total_usage_minutes"),
        ).where(active_equipment)
    )
    op_row = op_result.mappings().one()
    active_count = int(op_row["active_count"] or 0)
    total_usage_minutes = float(op_row["total_usage_minutes"] or 0.0)

    total_recorded = int(failure_row["total_recorded"] or 0)
    avg_downtime = (
        float(failure_row["average_downtime_hours"])
        if failure_row["average_downtime_hours"] is not None
        else None
    )
    total_downtime = round(float(failure_row["total_downtime_hours"] or 0.0), 2)

    if total_usage_minutes > 0:
        total_operating_hours = round(total_usage_minutes / 60.0, 1)
    else:
        total_operating_hours = round(max(active_count, 1) * 720.0, 1)

    mtbf_hours = round(total_operating_hours / max(total_recorded, 1), 1)
    mttr_hours = round(avg_downtime if avg_downtime is not None else 0.0, 1)
    denom = mtbf_hours + mttr_hours
    inherent_availability_pct = round((mtbf_hours / denom) * 100.0, 2) if denom > 0 else 100.0

    return {
        "total_recorded": total_recorded,
        "average_downtime_hours": avg_downtime,
        "total_downtime_hours": total_downtime,
        "total_operating_hours": total_operating_hours,
        "mtbf_hours": mtbf_hours,
        "mttr_hours": mttr_hours,
        "inherent_availability_pct": inherent_availability_pct,
    }


async def get_recent_activity(
    db: AsyncSession,
    limit: int,
) -> list[dict[str, Any]]:
    work_order_events = (
        select(
            WorkOrder.id.label("id"),
            literal("work_order").label("type"),
            case(
                (WorkOrder.status == WorkOrderStatus.pendiente, "OT pendiente"),
                (WorkOrder.status == WorkOrderStatus.en_proceso, "OT en proceso"),
                (WorkOrder.status == WorkOrderStatus.terminado, "OT terminada"),
                (WorkOrder.status == WorkOrderStatus.cancelado, "OT cancelada"),
                else_="Orden de trabajo",
            ).label("title"),
            func.substr(Maintenance.title, 1, 300).label("description"),
            WorkOrder.created_at.label("timestamp"),
            Equipment.tag_number.label("equipment_tag"),
        )
        .join(Maintenance, Maintenance.id == WorkOrder.maintenance_id)
        .join(Equipment, Equipment.id == Maintenance.equipment_id)
    )
    failure_events = select(
        FailureHistory.id.label("id"),
        literal("failure").label("type"),
        func.substr(FailureHistory.failure_mode, 1, 300).label("title"),
        func.substr(FailureHistory.description, 1, 300).label("description"),
        FailureHistory.created_at.label("timestamp"),
        Equipment.tag_number.label("equipment_tag"),
    ).join(Equipment, Equipment.id == FailureHistory.equipment_id)
    maintenance_events = select(
        MaintenanceHistory.id.label("id"),
        literal("maintenance").label("type"),
        literal("Mantenimiento ejecutado").label("title"),
        func.substr(MaintenanceHistory.action_taken, 1, 300).label(
            "description"
        ),
        MaintenanceHistory.execution_date.label("timestamp"),
        Equipment.tag_number.label("equipment_tag"),
    ).join(Equipment, Equipment.id == MaintenanceHistory.equipment_id)
    recommendation_events = select(
        AIRecommendation.id.label("id"),
        literal("recommendation").label("type"),
        func.substr(AIRecommendation.prediction_type, 1, 300).label("title"),
        func.substr(AIRecommendation.recommendation_text, 1, 300).label(
            "description"
        ),
        AIRecommendation.created_at.label("timestamp"),
        Equipment.tag_number.label("equipment_tag"),
    ).join(Equipment, Equipment.id == AIRecommendation.equipment_id)

    events = union_all(
        work_order_events,
        failure_events,
        maintenance_events,
        recommendation_events,
    ).subquery("dashboard_recent_activity")
    result = await db.execute(
        select(events)
        .order_by(events.c.timestamp.desc(), events.c.id.desc())
        .limit(limit)
    )
    return [dict(row) for row in result.mappings().all()]
