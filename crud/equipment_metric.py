import uuid
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.equipment_metric import EquipmentMetric
from schemas.equipment_metric import EquipmentMetricCreate

async def create_metric(db: AsyncSession, obj_in: EquipmentMetricCreate, recorded_by_id: uuid.UUID) -> EquipmentMetric:
    """Inserta una nueva lectura empírica o de sensor en el historial."""
    metric_data = obj_in.model_dump()
    # Inyectamos el ID del operario/sistema que está tomando la lectura (Desde el JWT)
    metric_data["recorded_by"] = recorded_by_id
    
    db_obj = EquipmentMetric(**metric_data)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_metrics_by_equipment(
    db: AsyncSession, equipment_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[EquipmentMetric]:
    """Obtiene el historial de lecturas de un equipo específico, ordenado de más reciente a más antiguo."""
    result = await db.execute(
        select(EquipmentMetric)
        .where(EquipmentMetric.equipment_id == equipment_id)
        .order_by(EquipmentMetric.recorded_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())

async def get_metric_by_id(db: AsyncSession, metric_id: uuid.UUID) -> EquipmentMetric | None:
    """Consulta una lectura específica por su ID único."""
    result = await db.execute(
        select(EquipmentMetric).where(EquipmentMetric.id == metric_id)
    )
    return result.scalars().first()