import uuid
import traceback
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from crud import equipment_metric as crud_metric
from schemas.equipment_metric import EquipmentMetricCreate
from models.equipment_metric import EquipmentMetric
from models.user import User

async def register_metric(db: AsyncSession, metric_in: EquipmentMetricCreate, current_user: User) -> EquipmentMetric:
    """
    Registra una lectura física. Captura violaciones de llave foránea 
    por si se intenta registrar a un equipment_id inexistente.
    """
    try:
        return await crud_metric.create_metric(db, obj_in=metric_in, recorded_by_id=current_user.id)
    except IntegrityError as e:
        await db.rollback()
        # Evaluamos si el error fue por el equipo no encontrado
        if "metrics_equipment_fkey" in str(e.orig):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El equipo al que intenta registrar la métrica no existe."
            )
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error de integridad de datos al registrar la métrica."
        )
    except Exception as e:
        await db.rollback()
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fallo inesperado al guardar la lectura: {str(e)}"
        )

async def get_equipment_history(
    db: AsyncSession, equipment_id: uuid.UUID, skip: int, limit: int
) -> list[EquipmentMetric]:
    """Retorna las lecturas históricas de una máquina."""
    return await crud_metric.get_metrics_by_equipment(db, equipment_id, skip, limit)