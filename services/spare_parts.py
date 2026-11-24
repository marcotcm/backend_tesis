"""
Capa de Servicios para Almacén MRO (Repuestos), Consumo en OTs y Alertas de Reposición.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.spare_part import SparePart, WorkOrderPart
from models.user import User
from models.work_orders import WorkOrder, WorkOrderStatus
from schemas.spare_part import (
    SparePartCreate,
    SparePartResponse,
    SparePartStockAdjust,
    SparePartUpdate,
    SparePartsSummary,
    WorkOrderPartConsumeRequest,
    WorkOrderPartResponse,
)
from services.notification import trigger_global_alert
from services.realtime_twin_hub import twin_hub


def _to_spare_part_response(part: SparePart) -> SparePartResponse:
    stock = float(part.stock_qty or 0.0)
    min_stock = float(part.min_stock_qty or 0.0)
    unit_cost = float(part.unit_cost or 0.0)
    return SparePartResponse(
        id=part.id,
        sku=part.sku,
        name=part.name,
        description=part.description,
        category=part.category,
        unit_of_measure=part.unit_of_measure,
        stock_qty=stock,
        min_stock_qty=min_stock,
        unit_cost=unit_cost,
        warehouse_location=part.warehouse_location,
        supplier=part.supplier,
        taxonomy_id=part.taxonomy_id,
        is_active=bool(part.is_active),
        is_low_stock=stock <= min_stock,
        inventory_value=round(stock * unit_cost, 2),
        created_by=part.created_by,
        created_at=part.created_at,
        updated_at=part.updated_at,
    )


async def _notify_low_stock_if_needed(db: AsyncSession, part: SparePart, user_id: Optional[uuid.UUID]) -> None:
    stock = float(part.stock_qty or 0.0)
    min_stock = float(part.min_stock_qty or 0.0)
    if stock <= min_stock:
        try:
            await trigger_global_alert(
                db=db,
                user_id=user_id,
                title=f"Alerta de Stock MRO: {part.sku}",
                message=(
                    f"El repuesto '{part.name}' ({part.sku}) alcanzó nivel crítico de reposición: "
                    f"{stock} {part.unit_of_measure} (mínimo: {min_stock})."
                ),
            )
        except Exception as err:
            print(f"[WARN MRO ALERTA] No se pudo emitir alerta de stock bajo: {err}")


async def list_spare_parts(
    db: AsyncSession,
    search: Optional[str] = None,
    category: Optional[str] = None,
    low_stock_only: bool = False,
    skip: int = 0,
    limit: int = 200,
) -> List[SparePartResponse]:
    stmt = select(SparePart).where(SparePart.is_active.is_(True))

    if search and search.strip():
        q = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                SparePart.sku.ilike(q),
                SparePart.name.ilike(q),
                SparePart.supplier.ilike(q),
                SparePart.warehouse_location.ilike(q),
            )
        )

    if category and category.strip() and category.strip().lower() != "all":
        stmt = stmt.where(SparePart.category == category.strip())

    if low_stock_only:
        stmt = stmt.where(SparePart.stock_qty <= SparePart.min_stock_qty)

    stmt = (
        stmt.order_by((SparePart.stock_qty <= SparePart.min_stock_qty).desc(), SparePart.name.asc())
        .offset(skip)
        .limit(limit)
    )
    res = await db.execute(stmt)
    return [_to_spare_part_response(p) for p in res.scalars().all()]


async def get_spare_parts_summary(db: AsyncSession) -> SparePartsSummary:
    stmt = select(
        func.count(SparePart.id).label("total_skus"),
        func.count(case((SparePart.stock_qty <= SparePart.min_stock_qty, 1))).label("low_stock_count"),
        func.count(case((SparePart.stock_qty <= 0, 1))).label("out_of_stock_count"),
        func.coalesce(func.sum(SparePart.stock_qty * SparePart.unit_cost), 0.0).label("total_inventory_value"),
    ).where(SparePart.is_active.is_(True))

    res = await db.execute(stmt)
    row = res.mappings().one()
    return SparePartsSummary(
        total_skus=int(row["total_skus"] or 0),
        low_stock_count=int(row["low_stock_count"] or 0),
        out_of_stock_count=int(row["out_of_stock_count"] or 0),
        total_inventory_value=round(float(row["total_inventory_value"] or 0.0), 2),
    )


async def create_spare_part(
    db: AsyncSession, part_in: SparePartCreate, current_user: User
) -> SparePartResponse:
    sku_clean = part_in.sku.strip()
    existing = await db.execute(select(SparePart).where(func.lower(SparePart.sku) == sku_clean.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un repuesto registrado con el SKU '{sku_clean}'.",
        )

    payload = part_in.model_dump()
    payload["sku"] = sku_clean
    payload["created_by"] = current_user.id

    db_part = SparePart(**payload)
    db.add(db_part)
    await db.commit()
    await db.refresh(db_part)

    await _notify_low_stock_if_needed(db, db_part, current_user.id)
    return _to_spare_part_response(db_part)


async def _get_part_or_404(db: AsyncSession, part_id: uuid.UUID) -> SparePart:
    res = await db.execute(select(SparePart).where(SparePart.id == part_id, SparePart.is_active.is_(True)))
    part = res.scalar_one_or_none()
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repuesto no encontrado.")
    return part


async def update_spare_part(
    db: AsyncSession, part_id: uuid.UUID, part_in: SparePartUpdate
) -> SparePartResponse:
    db_part = await _get_part_or_404(db, part_id)
    update_data = part_in.model_dump(exclude_unset=True)

    if "sku" in update_data and update_data["sku"] is not None:
        sku_clean = update_data["sku"].strip()
        dup = await db.execute(
            select(SparePart).where(
                func.lower(SparePart.sku) == sku_clean.lower(),
                SparePart.id != part_id,
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe otro repuesto con el SKU '{sku_clean}'.",
            )
        update_data["sku"] = sku_clean

    for field, value in update_data.items():
        setattr(db_part, field, value)
    db_part.updated_at = datetime.now(timezone.utc)

    db.add(db_part)
    await db.commit()
    await db.refresh(db_part)
    return _to_spare_part_response(db_part)


async def adjust_spare_part_stock(
    db: AsyncSession,
    part_id: uuid.UUID,
    adjust_in: SparePartStockAdjust,
    current_user: User,
) -> SparePartResponse:
    db_part = await _get_part_or_404(db, part_id)
    qty = Decimal(str(round(float(adjust_in.quantity), 2)))

    if adjust_in.operation == "subtract":
        upd_stmt = (
            update(SparePart)
            .where(SparePart.id == part_id, SparePart.is_active.is_(True), SparePart.stock_qty >= qty)
            .values(stock_qty=SparePart.stock_qty - qty, updated_at=datetime.now(timezone.utc))
            .returning(SparePart.id)
        )
        res = await db.execute(upd_stmt)
        if not res.first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stock insuficiente para descontar {float(qty)} {db_part.unit_of_measure}.",
            )
    elif adjust_in.operation == "add":
        await db.execute(
            update(SparePart)
            .where(SparePart.id == part_id)
            .values(stock_qty=SparePart.stock_qty + qty, updated_at=datetime.now(timezone.utc))
        )
    else:
        await db.execute(
            update(SparePart)
            .where(SparePart.id == part_id)
            .values(stock_qty=qty, updated_at=datetime.now(timezone.utc))
        )

    await db.commit()
    await db.refresh(db_part)
    await _notify_low_stock_if_needed(db, db_part, current_user.id)
    return _to_spare_part_response(db_part)


async def deactivate_spare_part(db: AsyncSession, part_id: uuid.UUID) -> dict:
    db_part = await _get_part_or_404(db, part_id)
    db_part.is_active = False
    db_part.updated_at = datetime.now(timezone.utc)
    db.add(db_part)
    await db.commit()
    return {"detail": f"Repuesto {db_part.sku} desactivado correctamente."}


async def list_work_order_parts(db: AsyncSession, wo_id: uuid.UUID) -> List[WorkOrderPartResponse]:
    wo_exists = await db.execute(select(WorkOrder.id).where(WorkOrder.id == wo_id))
    if not wo_exists.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orden de trabajo no encontrada.")

    stmt = (
        select(WorkOrderPart, SparePart)
        .join(SparePart, SparePart.id == WorkOrderPart.spare_part_id)
        .where(WorkOrderPart.work_order_id == wo_id)
        .order_by(WorkOrderPart.created_at.desc())
    )
    res = await db.execute(stmt)
    items: List[WorkOrderPartResponse] = []
    for usage, part in res.all():
        items.append(
            WorkOrderPartResponse(
                id=usage.id,
                work_order_id=usage.work_order_id,
                spare_part_id=usage.spare_part_id,
                spare_part_sku=part.sku,
                spare_part_name=part.name,
                unit_of_measure=part.unit_of_measure,
                quantity_used=float(usage.quantity_used),
                unit_cost_snapshot=float(usage.unit_cost_snapshot),
                total_cost=float(usage.total_cost),
                notes=usage.notes,
                created_at=usage.created_at,
            )
        )
    return items


async def _recalculate_work_order_parts_cost(db: AsyncSession, wo_id: uuid.UUID) -> float:
    sum_res = await db.execute(
        select(func.coalesce(func.sum(WorkOrderPart.total_cost), 0)).where(WorkOrderPart.work_order_id == wo_id)
    )
    parts_total = round(float(sum_res.scalar_one() or 0.0), 2)
    await db.execute(
        update(WorkOrder)
        .where(WorkOrder.id == wo_id)
        .values(parts_cost=Decimal(str(parts_total)), updated_at=datetime.now(timezone.utc))
    )
    return parts_total


async def consume_spare_part_for_work_order(
    db: AsyncSession,
    wo_id: uuid.UUID,
    req: WorkOrderPartConsumeRequest,
    current_user: User,
) -> WorkOrderPartResponse:
    wo_res = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    db_wo = wo_res.scalar_one_or_none()
    if not db_wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orden de trabajo no encontrada.")
    if db_wo.status == WorkOrderStatus.cancelado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pueden consumir repuestos en una orden de trabajo cancelada.",
        )

    db_part = await _get_part_or_404(db, req.spare_part_id)
    qty = Decimal(str(round(float(req.quantity_used), 2)))

    upd_stmt = (
        update(SparePart)
        .where(
            SparePart.id == req.spare_part_id,
            SparePart.is_active.is_(True),
            SparePart.stock_qty >= qty,
        )
        .values(stock_qty=SparePart.stock_qty - qty, updated_at=datetime.now(timezone.utc))
        .returning(SparePart.stock_qty, SparePart.unit_cost)
    )
    upd_res = await db.execute(upd_stmt)
    row = upd_res.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stock insuficiente para '{db_part.name}' (disponible: {float(db_part.stock_qty or 0)} {db_part.unit_of_measure}).",
        )

    unit_cost_dec = Decimal(str(round(float(row.unit_cost or 0), 2)))
    total_cost_dec = (qty * unit_cost_dec).quantize(Decimal("0.01"))

    usage = WorkOrderPart(
        work_order_id=wo_id,
        spare_part_id=req.spare_part_id,
        quantity_used=qty,
        unit_cost_snapshot=unit_cost_dec,
        total_cost=total_cost_dec,
        notes=req.notes,
        recorded_by=current_user.id,
    )
    db.add(usage)
    await db.flush()
    await _recalculate_work_order_parts_cost(db, wo_id)
    await db.commit()
    await db.refresh(usage)
    await db.refresh(db_part)

    await _notify_low_stock_if_needed(db, db_part, current_user.id)
    await twin_hub.broadcast_event("work_order_updated", {"work_order_id": str(wo_id), "status": db_wo.status})

    return WorkOrderPartResponse(
        id=usage.id,
        work_order_id=usage.work_order_id,
        spare_part_id=usage.spare_part_id,
        spare_part_sku=db_part.sku,
        spare_part_name=db_part.name,
        unit_of_measure=db_part.unit_of_measure,
        quantity_used=float(usage.quantity_used),
        unit_cost_snapshot=float(usage.unit_cost_snapshot),
        total_cost=float(usage.total_cost),
        notes=usage.notes,
        created_at=usage.created_at,
    )


async def remove_work_order_part(db: AsyncSession, wo_id: uuid.UUID, usage_id: uuid.UUID) -> dict:
    stmt = (
        select(WorkOrderPart, SparePart)
        .join(SparePart, SparePart.id == WorkOrderPart.spare_part_id)
        .where(WorkOrderPart.id == usage_id, WorkOrderPart.work_order_id == wo_id)
    )
    res = await db.execute(stmt)
    row = res.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registro de repuesto consumido no encontrado en esta orden.",
        )

    usage, part = row
    qty = Decimal(str(usage.quantity_used))
    await db.execute(
        update(SparePart)
        .where(SparePart.id == part.id)
        .values(stock_qty=SparePart.stock_qty + qty, updated_at=datetime.now(timezone.utc))
    )
    await db.delete(usage)
    await db.flush()
    parts_cost = await _recalculate_work_order_parts_cost(db, wo_id)
    await db.commit()

    await twin_hub.broadcast_event("work_order_updated", {"work_order_id": str(wo_id)})
    return {
        "detail": f"Consumo revertido y stock reintegrado a '{part.sku}'.",
        "parts_cost": parts_cost,
    }
