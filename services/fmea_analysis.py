import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from crud import equipment as crud_equipment
from crud import fmea_analysis as crud
from models.user import User
from schemas.fmea_analysis import FMEAAnalysisCreate, FMEAAnalysisUpdate


def calculate_rpn(severity: int, occurrence: int, detection: int) -> int:
    return severity * occurrence * detection


async def create(db: AsyncSession, data: FMEAAnalysisCreate, user: User):
    if not await crud_equipment.get_equipment_by_id(db, data.equipment_id):
        raise HTTPException(status_code=404, detail="El equipo no existe.")

    payload = data.model_dump()
    payload["created_by"] = user.id
    payload["rpn_score"] = calculate_rpn(payload["severity"], payload["occurrence"], payload["detection"])

    payload["causes"] = payload.get("causes") or []
    payload["effects"] = payload.get("effects") or []
    payload["current_controls"] = payload.get("current_controls") or []
    payload["recommended_actions"] = payload.get("recommended_actions") or []

    return await crud.create(db, payload)


async def get(db: AsyncSession, item_id: uuid.UUID):
    obj = await crud.get_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Análisis FMEA no encontrado.")
    return obj


async def update(db: AsyncSession, item_id: uuid.UUID, data: FMEAAnalysisUpdate, user: User):
    obj = await get(db, item_id)
    payload = data.model_dump(exclude_unset=True)

    if not payload:
        return obj

    if "severity" in payload or "occurrence" in payload or "detection" in payload:
        severity = payload.get("severity", obj.severity)
        occurrence = payload.get("occurrence", obj.occurrence)
        detection = payload.get("detection", obj.detection)
        payload["rpn_score"] = calculate_rpn(severity, occurrence, detection)

    payload["updated_at"] = datetime.now(timezone.utc)

    return await crud.update(db, obj, payload)
